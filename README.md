#Description

This is a websocket server implemented by python for RFC6455(http://tools.ietf.org/rfc/rfc6455.txt).


#How to use

1. To setup your websocket server, please import the WebSocketServer.py in your code and new an instance

2. You need specify your message dispatcher to handle the message received, such as:
################################################
class RequestDispatcher(object):
    '''
    Test dispacther for WebSockertServer
    '''


    def __init__(self):
        pass
        
    def dispatch(self, msg, client):
        if msg <> None:
            return msg
        else:
            print 'client ' + str(client.client_address) + ' is offline'
################################################

3. Pass the dispatcher instance to websocket server, and start the server.
################################################
if __name__ == '__main__':
    dispatcher = RequestDispatcher.RequestDispatcher()
    server = WebSocketServer.WebSocketServer(('0.0.0.0', 3398), dispatcher)
    server.serve_forever()
################################################


#Getting help:

If you have an issues with this server, please check the [issue tracker](http://github.com/miksago/node-websocket-server/issues).

- If you have an issue with a stacktrace / bug report, please submit an issue in the issue tracker, make sure to include details as to how to reproduce the issue.
- If you have a feature request, create an issue on the bug tracker and specifically state that it is a feature request, also send an email to alanlee1985@gmail.com referencing this feature request, discussion on feature requests should be done in the issue tracker.


