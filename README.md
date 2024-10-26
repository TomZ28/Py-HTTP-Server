# Py-HTTP-Server
A simple HTTP Server implemented in Python.

## Running the Server
Requires Python 3.10 or later.

To start the server, run the following command in a terminal:
```
python server.py <CacheExpiryTime:int> <SetLogging:bool>
```
Where:
 - `<CacheExpiryTime:int>`: How long caches last before they expire, in seconds
 - `<SetLogging:bool>`: Enable logging, either `false` (default) or `true`

Example:
```
python server.py 3600 true
```
This will start the server with a cache expiry time of 3600 seconds (1 hour) and with logging enabled.
