# Written by S. Mevawala, modified by D. Gitzel

import logging
import socket

import channelsimulator
import utils
import sys

import random
import math

MAX_Num_SEQ = 256

class Sender(object):

    def __init__(self, inbound_port=50006, outbound_port=50005, timeout=10, debug_level=logging.INFO):
        self.logger = utils.Logger(self.__class__.__name__, debug_level)

        self.inbound_port = inbound_port
        self.outbound_port = outbound_port
        self.simulator = channelsimulator.ChannelSimulator(inbound_port=inbound_port, outbound_port=outbound_port,
                                                           debug_level=debug_level)
        self.simulator.sndr_setup(timeout)
        self.simulator.rcvr_setup(timeout)

    def send(self, data):
        raise NotImplementedError("The base API class has no implementation. Please override and add your own.")


class BogoSender(Sender):

    def __init__(self):
        super(BogoSender, self).__init__()

    def send(self, data):
        self.logger.info("Sending on port: {} and waiting for ACK on port: {}".format(self.outbound_port, self.inbound_port))
        while True:
            try:
                self.simulator.u_send(data)  # send data
                ack = self.simulator.u_receive()  # receive ACK
                self.logger.info("Got ACK from socket: {}".format(
                    ack.decode('ascii')))  # note that ASCII will only decode bytes in the range 0-127
                break
            except socket.timeout:
                pass

class MySender(Sender):
    # Setting up some preliminary parameters
    Data_file = 0
    Max_Seg = 250  # Maximum Segment Size
    Num_segment = 0 # Segment Number
    partition = 0 # Number of partition 
    start = 0 # Start of partition
    end = Max_Seg  # End of partition
    Num_seq = random.randint(0, 255) # Pick a random sequence number to begin with
    
    # Setting up data buffer
    data_buffer = bytearray(MAX_Num_SEQ)
    Buffer_start = Num_seq
    Buffer_end = Num_seq

    num_duplicates = 0
    is_sent = False
    resend = False

    # Initialization
    def __init__(self, DATA, timeout = 0.1):
        super(MySender, self).__init__()
        self.Data_file = DATA
        self.timeout = timeout
        self.simulator.sndr_socket.settimeout(self.timeout)
        self.Num_segment = int(math.ceil(len(self.Data_file)/float(self.Max_Seg)))

    def send(self, data):
        self.logger.info("Sending on port: {} and waiting for ACK on port: {}".format(self.outbound_port, self.inbound_port))

        for s in self.splitSegment(self.Data_file, self.Max_Seg, self.partition):
            try:

                # two cases are handled: 1st sending data and timeout

                if not self.resend:
                    # Set up the format for sending segment
                    # The segment is in this format [ CHECKSUM | Num_SEQ | ACK_NUM | DATA]
                    seg = MySegment(Num_seq = 0, ack_num = 0, check_sum = 0, data = s)
                    seg.Num_seq = MySegment.seqNum(self, self.Num_seq, self.Max_Seg)
                    self.Num_seq = seg.Num_seq
                    seg.ack_num = 0

                    # The actual format for sending data
                    send_array = bytearray([seg.check_sum, seg.ack_num, seg.Num_seq])
                    send_array += s

                    # Define check_sum associated with data 
                    seg.check_sum = MySegment.checkSum(self, send_array)
                    send_array[0] = seg.check_sum

                    # Send the data       
                    self.simulator.u_send(send_array) 

                # Receiving from the receiver and figuring out what to do
                while True:
                    rcv_array = self.simulator.u_receive()

                    # ACK corrupted, resend data
                    if self.checkACK(rcv_array):
                        # Sequence number is correct 
                        if rcv_array[1] == self.Num_seq:
                            self.is_sent = True
                            self.simulator.u_send(send_array)  

                        # If ACK for subsequent segment comes in, know that the prev segment was also received
                        elif rcv_array[1] == (self.Num_seq + len(s)) % MAX_Num_SEQ: 
                            self.num_duplicates = 0
                            if self.timeout > 0.1:
                                self.timeout -= 0.1
                            self.simulator.sndr_socket.settimeout(self.timeout)
                            self.resend = False
                            break

                        # There was an error, resend     
                        else: 
                            self.simulator.u_send(send_array) 
                    
                    # ACK corrupted, resend data
                    else:
                        self.simulator.u_send(send_array) 
                        self.num_duplicates += 1
                        
                        # If the package was sent and there are three duplicate ACKs, wait longer
                        if self.num_duplicates == 3 and self.is_sent:
                            self.timeout *= 2
                            self.simulator.sndr_socket.settimeout(self.timeout) 
                            self.num_duplicates = 0
                            if self.timeout > 5:
                                print("Timeout")
                                exit()

            # If timeout, resend the data
            except socket.timeout:
                self.resend = True
                self.simulator.u_send(send_array)
                self.num_duplicates += 1
                if self.num_duplicates >= 3:
                    self.num_duplicates = 0
                    self.timeout *= 2
                    self.simulator.sndr_socket.settimeout(self.timeout)
                    if self.timeout > 5:
                        print("Timeout")
                        exit()                                           


    # Checks the checksum of the receiver ACK
    def checkACK(self, data):
        # checksum val is the inversion of the 1st element in data
        check_sum_val = ~data[0]
        for i in xrange(1, len(data)):
            # XOR of all elements in data  
            check_sum_val ^= data[i]
        if check_sum_val == -1: 
            return True 
        else:
            return False

    # Split up the segment into smaller segements
    def splitSegment(self, data, Max_Seg, partition):
        for i in range(self.Num_segment):
            partition += 1
            yield data[self.start:self.end]
            self.start = self.start + Max_Seg # New start of partition
            self.end = self.end + Max_Seg # New end of partition 



# The data is in this segment, along with error checking stuff 
class MySegment(object):

    def __init__(self, check_sum = 0, Num_seq = 0, ack_num = 0, data = []):
        self.check_sum = check_sum
        self.ack_num = ack_num
        self.Num_seq = Num_seq
        self.data = data

    @staticmethod
    def seqNum(self, prev_Num_seq, Max_Seg):
        return (prev_Num_seq + Max_Seg) % MAX_Num_SEQ

    # Make data into a byte array and then do the checksum 
    @staticmethod
    def checkSum(self, data):
        data_array = bytearray(data)
        check_sum_val = 0
        for i in xrange(len(data_array)):
            check_sum_val ^= data_array[i]
        return check_sum_val



if __name__ == "__main__":
    # test out BogoSender
    DATA = bytearray(sys.stdin.read())
    #sndr = BogoSender()
    sndr = MySender(DATA)
    sndr.send(DATA)