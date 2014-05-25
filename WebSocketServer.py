#coding = utf-8
'''
Created on 2013-1-9

@author: alan.lee
'''

import socket
import select
import Queue
import threading
import base64
import hashlib
import struct
import sys
import traceback

class Client(object):
    '''
    Agent of WebSocket client
    '''
    def __init__(self, connection, client_address):
        # for connection
        self.connection = connection
        self.client_address = client_address
        # for write queue
        self.wq = Queue.Queue()
        # for handshake
        self.handshake = False
        self.headers = dict()
        # for frame fragmentation
        self.frags = list()
        # for stats
        self.last_send = None
        self.last_recv = None
        self.send_counts = 0
        self.recv_counts = 0
    

class WebSocketServer(object):
    '''
    WebSocket server, can process request with threading
    the dispatcher will dispatch the message received
    dispatcher must have a function as dispatch(msg, client)
    if msg is None, the client will shutdown
    
    Call serve_forever to start the server.
    '''

    request_queue_size = 20
    allow_reuse_address = False
    
    def __init__(self, server_address, dispatcher, activate = True):
        self._server_address = server_address
        self._dispatcher = dispatcher
        self._is_shut_down = threading.Event()
        self._shutdown_request = False
        self._clients = dict()
        
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if activate:
            self.server_activate()
            
        self._inputs = list()
        self._outputs = list()
        self._exceptions = list()
        self._inputs.append(self._socket)
        
    def server_activate(self):
        if self.allow_reuse_address:
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(self._server_address)
        self._server_address = self._socket.getsockname()
        self._socket.listen(self.request_queue_size)
        
    def server_close(self):
        self._socket.close()
    
    def serve_forever(self, poll_interval=5):
        self._is_shut_down.clear()
        while not self._shutdown_request:
            rlist, wlist, elist = select.select(self._inputs, self._outputs, self._exceptions, poll_interval)
            if (rlist or wlist or elist):
                for r in rlist:
                    if r is self._socket:
                        connection, client_address = self._socket.accept()
                        connection.setblocking(0)
                        client = Client(connection, client_address)
                        self._clients[connection] = client
                        self._inputs.append(connection)
                        self._exceptions.append(connection)
                    else:
                        client = self._clients[r]
                        assert r is client.connection
                        if self._verify_handshake(r, client):
                            try:
                                raw_data = self._get_raw_data(connection)
                                if len(raw_data) >= 2:
                                    t = threading.Thread(target = self._process_data,
                                                     args = (raw_data, client))
                                    t.daemon = False
                                    t.start()
                                else:
                                    self._close_client(client);
                            except:
                                self._handle_error(r, client)
                                
                for w in wlist:
                    client = self._clients[w]
                    assert w is client.connection
                    while not client.wq.empty():
                        data = client.wq.get_nowait()
                        print '---------------send to ' + str(client.client_address) + '-----------------'
                        print data
                        print '---------------------------------------------------------------------'
                        w.sendall(data)
                    if  client.wq.empty() and w in self._outputs:
                        self._outputs.remove(w)
                        
                for e in elist:
                    client = self._clients[e]
                    assert e is client.connection
                    self._close_client(client)
                    
            for client in self._clients.values():
                if client.wq.not_empty:
                    self._outputs.append(client.connection)
                    
    def _verify_handshake(self, connection, client):
        if not client.handshake:
            raw_request = self._get_raw_data(connection)
            t = threading.Thread(target = self._handshake, 
                                 args = (raw_request, client))
            t.daemon = False
            t.start()
        return client.handshake
    
    def _handshake(self, raw_request, client):
        headers = dict()
        response = ''
        
        try:
            header_lines = raw_request.split('\r\n\r\n', 1)[0].split("\r\n")
            command, path, version = header_lines[0].split()
            
            if cmp(command.upper(), 'GET'):
                raise Exception('HTTP Command Error!')
            
            if cmp(version[:5].upper(), 'HTTP/'):
                raise Exception('HTTP Protocol Error!')
            
            version_number = version.split('/', 1)[1].split(".")
            if version_number[0] < 1 or (version_number[0] == 1 and version_number[1] < 1):
                raise Exception('HTTP Version Error!')
            
            for line in header_lines[1:]:  
                key, value = line.split(":", 1)
                headers[key] = value.strip()  
            
            if not headers.has_key('Sec-WebSocket-Key'):    
                raise Exception('Lack header Sec-WebSocket-Key!')
           
            if not headers.has_key('Host'):
                raise Exception('Lack header Host!')
            
            if not headers.has_key('Upgrade'):
                raise Exception('Lack header Upgrade!')
            elif cmp(headers['Upgrade'].lower(), 'websocket'):
                raise Exception('Header Upgrade should be websocket!')
            
            if not headers.has_key('Connection'):
                raise Exception('Lack header Connection!')
            elif cmp(headers['Connection'].lower(), 'upgrade'):
                raise Exception('Header Connection should be Upgrade!')
            
            if  not '13' in headers['Sec-WebSocket-Version'].split(','):
                raise Exception('Sec-WebSocket-Version shoule be 13')
          
            key = base64.b64encode(hashlib.sha1(headers["Sec-WebSocket-Key"] + 
                                '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())  
                
            response += 'HTTP/1.1 101 Switching Protocols\r\n' \
                        'Upgrade:websocket\r\n'\
                        'Connection: Upgrade\r\n'\
                        'Sec-WebSocket-Accept:'+ key + '\r\n\r\n'
            
            headers['Command'] = command
            headers['Path'] = path
            headers['Version'] = version
            client.headers.update(headers)
            client.handshake = True
        except Exception, e:
            print str(e)
            etype, value, tb = sys.exc_info()
            print traceback.format_exception(etype, value, tb)
            response += 'HTTP/1.1 400 Bad Request\r\n' \
                        'Sec-WebSocket-Version:13\r\n\r\n'
            client.handshake = False
        finally:
            client.wq.put_nowait(response)
            return client.handshake
        
    def _process_data(self, raw_data, client):
        f = WSFrame(raw_data)
        if f.fin == 0:
            client.frags.append(f)
            return
        
        if f.opcode == 0x0: 
            #fin=1 & opcode=0
            client.frags.append(f)
            assert len(client.frags) > 1
            f = client.frags[0]
            for i in (1, len(client.frags)):
                f.payload.extend(client.frags[i].payload)
        
        if f.opcode == 0x1 or f.opcode == 0x02:
            msg = f.get_msg()
            ret = self._dispatcher.dispatch(msg, client)
            if ret is not None:
                self._send_frame(client, 0x1, ret)
        elif f.opcode == 0x8:
            self._close_client(client)
        elif f.opcode == 0x9:
            self._process_ping(f, client)
        elif f.opcode == 0xa:
            self._process_pong(f, client)
            
    def _close_client(self, client):
        c = client.connection
        if c in self._inputs:
            self._inputs.remove(c)
        if c in self._outputs:
            self._outputs.remove(c)
        if c in self._exceptions:
            self._exceptions.remove(c)
        self._clients.pop(c, None)
        c.close()
        self._dispatcher.dispatch(None, client)
        
    def _process_ping(self, frame, client):
        self._send_frame(client, 0xa, frame.payload, frame.mask_code)
    
    def _process_pong(self, frame, client):
        if frame.length > 0:
            msg = frame.get_msg()
            self._dispatcher.dispatch(msg, client)
        
    def _send_frame(self, client, opcode, data, mask = None, frags = False, frag_size = 0):
        length = len(data)
        if frags and frag_size <> 0:
            frag_count = length / frag_size + 1
            for i in range(1, frag_count):
                frag_fin = 0x0
                frag_opcode = 0x0
                frag_data_start = (i - 1) * frag_size
                frag_data_end = i * frag_size > length and i * frag_size - 1 or length - 1 
                frag_data = data[frag_data_start, frag_data_end]
                if i == 1:
                    frag_opcode = opcode
                if i == frag_count:
                    frag_fin = 0x1
                frame = self._build_frame(frag_fin, frag_opcode, frag_data, mask)
                client.wq.put_nowait(frame)
        else:
            frame = self._build_frame(0x1, opcode, data, mask)
            client.wq.put_nowait(frame)
        
    def _build_frame(self, fin, opcode, data, mask = None):
        fheader = ''
        length = len(data)
        first_byte = (fin << 7) + opcode
        second_byte = 0
        if mask:
            second_byte = 0x1 << 7
           
        if length < 126:
            second_byte += length
            fheader = struct.pack('BB', first_byte, second_byte)
        elif length < 0xffff:
            second_byte += 126
            if mask:
                fheader = struct.pack('!BBHI', first_byte, second_byte, length, mask)
            else:
                fheader = struct.pack('!BBH', first_byte, second_byte, length)
        else:
            second_byte += 127
            if mask:
                fheader = struct.pack('!BBQI', first_byte, second_byte, length, mask)
            else:
                fheader = struct.pack('!BBQ', first_byte, second_byte, length)
                
        return ''.join((fheader, data))
                  
    def _get_raw_data(self, connection):
        #rfile = connection.makefile('rb', -1)
        #raw_request = rfile.readlines(65537)
        raw_request = connection.recv(65537)
        print '-----------------------------received data------------------------------'
        print raw_request
        print '------------------------------------------------------------------------'
        if len(raw_request) > 65536 and len(raw_request) <= 0:
            raise Exception('the request is too long.')
        return raw_request
    
    def _handle_error(self, connection, client):
        pass
    
    def shutdown(self, server_close = True):
        """Stops the serve_forever loop.

        Blocks until the loop has finished. This must be called while
        serve_forever() is running in another thread, or it will
        deadlock.
        """
        self._shutdown_request = True
        self._is_shut_down.wait()
        if server_close:
            self.server_close()

class WSFrame(object):
    '''
    http://tools.ietf.org/rfc/rfc6455.txt
      0                   1                   2                   3
      0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
     +-+-+-+-+-------+-+-------------+-------------------------------+
     |F|R|R|R| opcode|M| Payload len |    Extended payload length    |
     |I|S|S|S|  (4)  |A|     (7)     |             (16/64)           |
     |N|V|V|V|       |S|             |   (if payload len==126/127)   |
     | |1|2|3|       |K|             |                               |
     +-+-+-+-+-------+-+-------------+ - - - - - - - - - - - - - - - +
     |     Extended payload length continued, if payload len == 127  |
     + - - - - - - - - - - - - - - - +-------------------------------+
     |                               |Masking-key, if MASK set to 1  |
     +-------------------------------+-------------------------------+
     | Masking-key (continued)       |          Payload Data         |
     +-------------------------------- - - - - - - - - - - - - - - - +
     :                     Payload Data continued ...                :
     + - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - +
     |                     Payload Data continued ...                |
     +---------------------------------------------------------------+
    '''
    def __init__(self, raw): 
        self.fin = ord(raw[0]) >> 7
        self.opcode = ord(raw[0]) & 0x0f
        self.mask = ord(raw[1]) >> 7
        self.length = ord(raw[1]) & 0x7f
        offset = 2
        if self.length == 126:
            self.length = ord(raw[2]) >> 8 + ord(raw[3])# big endian???
            offset = 4
        elif self.length == 127:
            self.length = 0
            for i in range(2, 9):
                self.length <<= 8
                self.length += ord(raw[i])
            offset = 10
        if self.mask:
            self.mask_code = raw[offset : offset + 4]
            offset += 4
        
        assert len(raw) >= offset + self.length
        self.payload = raw[offset: offset + self.length]
        
    def get_msg(self):
        msg = ''
        i = 0
        if self.mask:
            for c in self.payload:
                msg += chr(ord(c) ^ ord(self.mask_code[i % 4]))
                i += 1
        else:
            msg = self.payload
        #if self.opcode == 0x1: #UTF-8 text
        #    msg = msg.decode('utf-8')
        return msg        
