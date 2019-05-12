# Written by S. Mevawala, modified by D. Gitzel

import logging

import channelsimulator
import utils
import sys
import socket

class Receiver(object):

    def __init__(self, inbound_port=50005, outbound_port=50006, timeout=10, debug_level=logging.INFO):
        self.logger = utils.Logger(self.__class__.__name__, debug_level)

        self.inbound_port = inbound_port
        self.outbound_port = outbound_port
        self.simulator = channelsimulator.ChannelSimulator(inbound_port=inbound_port, outbound_port=outbound_port,
                                                           debug_level=debug_level)
        self.simulator.rcvr_setup(timeout)
        self.simulator.sndr_setup(timeout)

    def receive(self):
        raise NotImplementedError("The base API class has no implementation. Please override and add your own.")


class BogoReceiver(Receiver):
    ACK_DATA = bytes(123)

    def __init__(self):
        super(BogoReceiver, self).__init__()

    def receive(self):
        self.logger.info("Receiving on port: {} and replying with ACK on port: {}".format(self.inbound_port, self.outbound_port))
        while True:
            try:
                 data = self.simulator.u_receive()  # receive data
                 self.logger.info("Got data from socket: {}".format(
                     data.decode('ascii')))  # note that ASCII will only decode bytes in the range 0-127
	         sys.stdout.write(data)
                 self.simulator.u_send(BogoReceiver.ACK_DATA)  # send ACK
            except socket.timeout:
                sys.exit()

class MyReceiver(Receiver):
    # Initialization all variables
    rcv_array = bytearray([0,0,0,0])
    last_acknum = -1 
    ACK_backup = bytearray([0,0,0])
    resend = True
    num_duplicates = 0


    def __init__(self, timeout = 0.1):
        super(MyReceiver, self).__init__()
        self.timeout = timeout
        self.simulator.rcvr_socket.settimeout(self.timeout)

    def receive(self):
        while True:
            try:
                # Receive data and check the timeout 
                self.rcv_array = self.simulator.u_receive()
                if self.timeout > 0.1:
                    self.timeout += -(0.1)
                    self.num_duplicates = 0

                # Send the ACK 
                self.send()

            # If timeout, resend the the back-up ack
            except socket.timeout:
                self.resend = True
                self.simulator.u_send(self.ACK_backup)
                self.num_duplicates += 1
                # Handle the case of too many dups
                if self.num_duplicates >= 3:
                    self.num_duplicates = 0
                    self.timeout *= 2
                    self.simulator.rcvr_socket.settimeout(self.timeout)
                    if self.timeout > 5:
                        exit()
                        
    def send(self):
        # Create an ACK to be sent
        ACK_seg = mysegment()
        ACK_success = ACK_seg.ack(self.rcv_array, self.last_acknum)
        if ACK_success:
            self.last_acknum = ACK_seg.ACK_num
        if ACK_seg.ACK_num < 0:
            ACK_seg.ACK_num = 0 # Might be set back to -1
        ACK_seg.check_sum = ACK_seg.checkSum()
        rcv_array = bytearray([ACK_seg.check_sum, ACK_seg.ACK_num])
        ACK_backup = rcv_array
        self.simulator.u_send(rcv_array)

class mysegment(object):

    def __init__(self, check_sum = 0, seq_num = 0, ACK_num = 0, data = []):
        self.check_sum = check_sum
        self.seq_num = seq_num
        self.ACK_num = ACK_num
        self.data = data
         
    # receiver's segment checksum will just be the ack number
    def checkSum(self):        
        return self.ACK_num
        

    # Checks the checksum (i.e. the ACK number in this case)
    def checkACK(self,data):
        # Invert all the bits in the first row of the data array (i.e. the checksum row)         
        check_sum_val =~ data[0]    
        for i in xrange(1,len(data)):
            # XOR all elements of data, similar for sender
            check_sum_val ^= data[i]
        if check_sum_val ==- 1:
            # -1 means being valid
            return True
        else:
            return False
    
    # Checks if the ACK is valid 
    def ack(self, data, last_acknum):
        we_going_to_standings = self.checkACK(data)
        if we_going_to_standings:
            self.ACK_num = (data[2] + len(data[3:])) % 256
            if data[2] == last_acknum or last_acknum == -1:
                sys.stdout.write("{}".format(data[3:]))
                sys.stdout.flush()
                return True
        else:
            pass

        return False

if __name__ == "__main__":
    # test out BogoReceiver
    #rcvr = BogoReceiver()
    rcvr = MyReceiver()
    rcvr.receive()
