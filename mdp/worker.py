# -*- coding: utf-8 -*-

"""Module containing worker functionality for the MDP implementation.

For the MDP specification see: http://rfc.zeromq.org/spec:7
"""

__license__ = """
    This file is part of MDP.

    MDP is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    MDP is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with MDP.  If not, see <http://www.gnu.org/licenses/>.
"""

__author__ = 'Guido Goldstein'
__email__ = 'gst-py@a-nugget.de'


import sys
import time
from exceptions import UserWarning
from pprint import pprint

import zmq
from zmq.eventloop.zmqstream import ZMQStream
from zmq.eventloop.ioloop import IOLoop, DelayedCallback, PeriodicCallback

from util import split_address

###

class ConnectionNotReadyError(RuntimeError):
    """Exception raised when attempting to use the MDPWorker before the handshake took place.
    """
    pass
#

class MissingHeartbeat(UserWarning):
    """Exception raised when a heartbeat was not received on time.
    """
    pass
#
###

class MDPWorker(object):

    """Class for the MDP worker side.

    Thin encapsulation of a zmq.XREQ socket.
    Provides a send method with optional timeout parameter.

    Will use a timeout to indicate a broker failure.
    """

    _proto_version = b'MDPW01'

    # TODO: integrate that into API
    HB_INTERVAL = 1000  # in milliseconds
    HB_LIVENESS = 3    # HBs to miss before connection counts as dead

    def __init__(self, context, endpoint, service):
        """Initialize the MDPWorker.

        context is the zmq context to create the socket from.
        service is a byte-string with the service name.
        """
        self.context = context
        self.endpoint = endpoint
        self.service = service
        self.stream = None
        self._tmo = None
        self.need_handshake = True
        self.ticker = None
        self._delayed_cb = None
        self._create_stream()
        return

    def _create_stream(self):
        """Helper to create the socket and the stream.
        """
        socket = self.context.socket(zmq.XREQ)
        ioloop = IOLoop.instance()
        self.stream = ZMQStream(socket, ioloop)
        self.stream.on_recv(self._on_message)
        self.stream.socket.setsockopt(zmq.LINGER, 0)
        self.stream.connect(self.endpoint)
        self.ticker = PeriodicCallback(self._tick, self.HB_INTERVAL)
        self._send_ready()
        self.ticker.start()
        return

    def _send_ready(self):
        """Helper method to prepare and send the workers READY message.
        """
        ready_msg = [ b'', self._proto_version, chr(1), self.service ]
        self.stream.send_multipart(ready_msg)
        self.curr_liveness = self.HB_LIVENESS
        return

    def _tick(self):
        """Method called every HB_INTERVAL milliseconds.
        """
        self.curr_liveness -= 1
##         print '%.3f tick - %d' % (time.time(), self.curr_liveness)
        self.send_hb()
        if self.curr_liveness >= 0:
            return
        print '%.3f lost connection' % time.time()
        # ouch, connection seems to be dead
        self.shutdown()
        # try to recreate it
        self._delayed_cb = DelayedCallback(self._create_stream, 5000)
        self._delayed_cb.start()
        return

    def send_hb(self):
        """Construct and send HB message to broker.
        """
        msg = [ b'', self._proto_version, chr(4) ]
        self.stream.send_multipart(msg)
        return

    def shutdown(self):
        """Method to deactivate the worker connection completely.

        Will delete the stream and the underlying socket.
        """
        if self.ticker:
            self.ticker.stop()
            self.ticker = None
        if not self.stream:
            return
        self.stream.socket.close()
        self.stream.close()
        self.stream = None
        self.timed_out = False
        self.need_handshake = True
        self.connected = False
        return

    def reply(self, msg):
        """Send the given message.

        msg can either be a byte-string or a list of byte-strings.
        """
##         if self.need_handshake:
##             raise ConnectionNotReadyError()
        # prepare full message
        to_send = self.envelope
        self.envelope = None
        if isinstance(msg, list):
            to_send.extend(msg)
        else:
            to_send.append(msg)
        self.stream.send_multipart(to_send)
        return

    def _on_message(self, msg):
        """Helper method called on message receive.

        msg is a list w/ the message parts
        """
        # 1st part is empty
        msg.pop(0)
        # 2nd part is protocol version
        # TODO: version check
        proto = msg.pop(0)
        # 3nd part is message type
        msg_type = msg.pop(0)
        # XXX: hardcoded message types!
        # any message resets the liveness counter
        self.need_handshake = False
        self.curr_liveness = self.HB_LIVENESS
        if msg_type == '\x05': # disconnect
            print '    DISC'
            self.curr_liveness = 0 # reconnect will be triggered by hb timer
        elif msg_type == '\x02': # request
            # remaining parts are the user message
            envelope, msg = split_address(msg)
            envelope.append(b'')
            envelope = [ b'', self._proto_version, '\x03'] + envelope # REPLY
            self.envelope = envelope
            self.on_request(msg)
        else:
            # invalid message
            # ignored
            pass
        return

    def on_request(self, msg):
        """Public method called when a request arrived.

        Must be overloaded!
        """
        pass
#

### Local Variables:
### buffer-file-coding-system: utf-8
### mode: python
### End:
