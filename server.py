import sys
import os
import time
import socket
import select
import os

if not len(sys.argv) >= 2 or not sys.argv[1].isdigit():
    print("Usage: python server.py <CacheExpiryTime:int> <SetLogging:bool>")
    sys.exit()

# Cache expiry time
cache_exp_time_str = sys.argv[1]
cache_exp_time = int(cache_exp_time_str)
cache_exp_time_nbytes = 128
cache_exp_time_byteorder = "big"

# Logging
logging = len(sys.argv) >= 3 and sys.argv[2].lower() == "true"
log_filename = os.path.dirname(os.path.realpath(__file__)) + "\server.log"

# Server socket
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setblocking(False)
server_address = ('localhost', 8888)
server.bind(server_address)
server.listen(10)

# Select objects (readable, writable, exceptions)
inputs = [server]
outputs = []

# Client/Host mappings
clients = {}
hosts = {}
clients_and_hosts_map = {}

# Client/Host data
msg_queues = {}
byte_data = {}
parsed_headers = {}
content_lengths = {}
has_content_lengths = {}
cache_filenames = {}
write_to_cache = {}

def is_valid_request(data_str: str) -> str:
    """
    Returns: True if and only if the request is a non-referer GET request,
    and False otherwise.
    """
    # Check if `data_str` is a GET request
    is_get_request = data_str[:3] == "GET"

    # Check if `data_str` is not a request relative to a referer
    is_referer_request = False
    has_referer_header = data_str.find("Referer: ") != -1

    if has_referer_header:
        referer_str = "Referer: "
        referer_str_index = data_str.find(referer_str)
        remaining_str = data_str[referer_str_index+len(referer_str):]
        referer_end_index = remaining_str.find("\r\n")

        host = remaining_str[:referer_end_index].split("/")[3]

        # Extract the host. If it doesn't match, it's a referer link
        host_str = "Host: "
        host_str_index = data_str.find(host_str)
        host_start_index = host_str_index+len(host_str)

        if (
            data_str.find(referer_str) != -1 and
            data_str[host_start_index:host_start_index+len(host)] != host and
            not data_str[len("GET /"):len("GET /")+len(host)] == host
        ):
            is_referer_request = True
    
    return is_get_request and not is_referer_request

def modify_get_host_path(data_str: str) -> str:
    """
    Returns: A copy of data_str with the host and path modified, in addition to
    the new host and path.
    """
    data_path_index = 1
    data_host_index = 3

    split_data = data_str.split(" ")
    full_link = split_data[data_path_index][1:]

    link_path_index = full_link.find("/")
    if link_path_index >= 0:
        link_host = full_link[:link_path_index]
        link_path = full_link[link_path_index:]
    else:
        link_host = full_link
        link_path = "/"
    
    split_data[data_path_index] = link_path
    split_data[data_host_index] = link_host + "\r\nConnection:"

    return " ".join(split_data), link_host, link_path

def get_cache_filename(host: str, path: str) -> str:
    return os.path.dirname(os.path.realpath(__file__)) + "\\" + host + path.replace("/", "_") + "_cachefile"

def create_cache(client_connection):
    """
    Writes the expiry time and data to a cachefile.
    In this cachefile, the first `cache_exp_time_nbytes` contains the
    cache expiry time, written in a `cache_exp_time_byteorder` byteorder.
    The remaining data will contain the target host/path data.
    """
    try:
        f = open(cache_filenames[client_connection], "wb")
        f.write(cache_exp_time.to_bytes(cache_exp_time_nbytes, cache_exp_time_byteorder))
        f.write(byte_data[clients_and_hosts_map[client_connection]])
        f.close()
    except:
        print("Unable to write to cache")

def get_cache_data_exp(cache_filename: str) -> tuple[bytes | None, bool]:
    """
    Returns the cached target host/path data, and whether it is expired or not.
    See the `create_cache()` function docstring for information on the
    cachefile structure.
    """
    try:
        f = open(cache_filename, "rb")
        cached_expiry_time = int.from_bytes(f.read(cache_exp_time_nbytes), cache_exp_time_byteorder)
        cached_data = f.read()
        f.close()
        is_expired = time.time() - os.path.getmtime(cache_filename) >= cached_expiry_time
        return cached_data, is_expired
    except:
        return None, True

def write_to_log(data: str) -> None:
    """
    If logging is enabled, write to log file. Does nothing otherwise.
    """
    if logging:
        try:
            f = open(log_filename, "a")
            f.write("[{}] ".format(time.ctime()) + data + "\n")
            f.close()
        except:
            return

def get_content_length(data_str: str) -> int:
    """
    If there is a `Content-Length` header in `data_str`, return its value.
    Otherwise, return -1.
    """
    content_length_str = "Content-Length: "
    content_length_index = data_str.find(content_length_str)
    if content_length_index == -1:
        return -1
    remaining_str = data_str[content_length_index + len(content_length_str):]
    value_end_index = remaining_str.find("\r\n")
    return int(remaining_str[:value_end_index])

def cleanup_client_connection(client_connection: socket.socket) -> None:
    if client_connection in clients_and_hosts_map:
        del byte_data[clients_and_hosts_map[client_connection]]
        del clients_and_hosts_map[client_connection]
    if s in cache_filenames:
        del cache_filenames[s]
    if s in write_to_cache:
        del write_to_cache[s]
    del clients[client_connection]
    del byte_data[client_connection]
    del msg_queues[client_connection]

def cleanup_host_connection(host_connection: socket.socket) -> None:
    del hosts[host_connection]
    del clients_and_hosts_map[host_connection]
    del parsed_headers[host_connection]
    del content_lengths[host_connection]
    del has_content_lengths[host_connection]
    del msg_queues[host_connection]

# If logging is enabled, indicate server start time
if logging:
    write_to_log("SERVER START")
    print("Logging enabled.")
print("Server started.")

while inputs:
    readable, writable, exceptional = select.select(inputs, outputs, inputs)

    for s in readable:
        if s is server:
            connection, client_address = s.accept()
            connection.setblocking(False)
            inputs.append(connection)
            clients[connection] = True
            byte_data[connection] = b''
            msg_queues[connection] = []
            write_to_log("Connected to {}".format(client_address))
        else:
            data_chunk = s.recv(1024)
            
            if s in clients:
                if data_chunk:
                    byte_data[s] += data_chunk
                    write_to_log("Received data chunk of size {} from {}:\n{}".format(
                        len(data_chunk),
                        s.getsockname(),
                        data_chunk.decode(errors="replace")
                    ))
                
                if not data_chunk or data_chunk[-len(b'\r\n\r\n'):] == b'\r\n\r\n':
                    inputs.remove(s)
                    data_str = byte_data[s].decode(errors="ignore")
                    
                    if is_valid_request(data_str):
                        modified_data_str, host, path = modify_get_host_path(data_str)
                        cache_filename = get_cache_filename(host, path)
                        cache_filenames[s] = cache_filename
                        cached_data, cache_is_expired = get_cache_data_exp(cache_filename)

                        if cache_is_expired:
                            # Indicate that a cache write should occur for the target host/path
                            write_to_cache[s] = True

                            # Initialize the target host connection
                            host_connection = socket.create_connection((host, 80))
                            host_connection.setblocking(False)
                            hosts[host_connection] = True
                            msg_queues[host_connection] = [modified_data_str.encode()]
                            clients_and_hosts_map[s] = host_connection
                            clients_and_hosts_map[host_connection] = s
                            byte_data[host_connection] = b''
                            parsed_headers[host_connection] = False
                            content_lengths[host_connection] = -1
                            has_content_lengths[host_connection] = False
                            outputs.append(host_connection)

                            write_to_log("Cache write for {}".format(host + path))
                        else:
                            msg_queues[s].append(cached_data)
                        outputs.append(s)
                    else:
                        write_to_log("Closed connection to {}".format(s.getsockname()))
                        cleanup_client_connection(s)
                        s.close()

            elif s in hosts:
                if data_chunk:
                    # Ensure all headers are read to determine the conditions
                    # for ending the host connection
                    if not parsed_headers[s]:
                        data_chunk_str = data_chunk.decode(errors="replace")
                        body_start = data_chunk_str.find("\r\n\r\n") + len("\r\n\r\n")
                        body_start_at_end = body_start == len(data_chunk_str)
                        content_length = get_content_length(data_chunk_str)
                        if content_length != -1:
                            content_lengths[s] = content_length
                            has_content_lengths[s] = True
                        if has_content_lengths[s] or body_start != -1:
                            parsed_headers[s] = True
                    else:
                        body_start = 0
                        body_start_at_end = False
                    msg_queues[clients_and_hosts_map[s]].append(data_chunk)
                    byte_data[s] += data_chunk
                    content_lengths[s] -= len(data_chunk[body_start:])

                    write_to_log("Received data chunk of size {} from {}:\n{}".format(
                        len(data_chunk),
                        s.getpeername(),
                        data_chunk.decode(errors="replace")
                    ))

                    # If the `Content-Length` was set, end the host connection
                    # when all data has been read. Otherwise, end the host
                    # connection when a double carriage return is found at the
                    # end of the response body.
                    if (has_content_lengths[s] and content_lengths[s] <= 0) or \
                        (not has_content_lengths[s] and \
                         not body_start_at_end and \
                            data_chunk[-len(b'\r\n\r\n'):] == b'\r\n\r\n'):
                        inputs.remove(s)
                        write_to_log("Closed connection to {}".format(s.getpeername()))
                        cleanup_host_connection(s)
                        s.close()

                else:
                    inputs.remove(s)
                    write_to_log("Closed connection to {}".format(s.getpeername()))
                    cleanup_host_connection(s)
                    s.close()    

            else:
                inputs.remove(s)
                if s in outputs:
                    outputs.remove(s)
                write_to_log("Closed connection to {}".format(s.getsockname()))
                s.close()
    
    for s in writable:
        if len(msg_queues[s]) > 0:
            if s in clients:
                host_data = msg_queues[s].pop(0)
                s.sendall(host_data)

                write_to_log("Sent data chunk of size {} to {}:\n{}".format(
                    len(host_data),
                    s.getsockname(),
                    host_data.decode(errors="replace")
                ))

                # Once all the data received from the target host has been
                # sent to the client, we can close the client connection.
                if (s not in clients_and_hosts_map or \
                    clients_and_hosts_map[s] not in clients_and_hosts_map) and \
                    len(msg_queues[s]) == 0:
                    outputs.remove(s)
                    
                    # If indicated, write to a cache file as all the data has
                    # been received.
                    if s in write_to_cache:
                        create_cache(s)
                        write_to_log("Cache write for {}".format(s.getsockname()))
                    write_to_log("Closed connection to {}".format(s.getsockname()))
                    cleanup_client_connection(s)
                    s.close()
            elif s in hosts:
                client_request = msg_queues[s].pop()
                s.sendall(client_request)

                write_to_log("Sent data chunk of size {} to {}:\n{}".format(
                    len(client_request),
                    s.getpeername(),
                    client_request.decode(errors="replace")
                ))
                
                outputs.remove(s)
                inputs.append(s)
            else:
                outputs.remove(s)
                if s in inputs:
                    inputs.remove(s)
                write_to_log("Closed connection to {}".format(s.getsockname()))
                s.close()
    
    for s in exceptional:
        inputs.remove(s)
        if s in outputs:
            outputs.remove(s)
        if s in clients:
            cleanup_client_connection(s)
            write_to_log("Closed connection to {}".format(s.getsockname()))
        elif s in hosts:
            cleanup_host_connection(s)
            write_to_log("Closed connection to {}".format(s.getpeername()))
        else:
            write_to_log("Closed connection to {}".format(s.getsockname()))
        s.close()
