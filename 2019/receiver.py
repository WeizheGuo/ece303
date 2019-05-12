# -*- coding: utf8 -*-
# Written by S. Mevawala, modified by D. Gitzel

import logging

import channelsimulator
import utils
import sys
import socket

import hashlib
from collections import namedtuple
from collections import OrderedDict
from threading import Thread
import struct
import random
import math

class Receiver(object):

    #def __init__(self, inbound_port=50005, outbound_port=50006, timeout=10, debug_level=logging.INFO):
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

class MyReceiver(BogoReceiver):
    def __init__(self):
        super(MyReceiver, self).__init__()
        self.sequence_bits = 30
        self.timeout = 1
        self.windowSize = 16

    def receive(self):
        self.logger.info("Receiving on port: {} and replying with ACK on port: {}".format(self.inbound_port, self.outbound_port))
        # Use sliding window to handle received packet
        window = Window(self.sequence_bits, self.windowSize)

        packetHandler = PacketHandler(self.simulator, window, self.logger, self.timeout)

        # Start thread execution
        packetHandler.start()

        # Wait for a thread to finish its execution
        packetHandler.join()


class Window(object):
    """
    Window function for packet handling
    """

    def __init__(self, sequence_bits, windowSize=None):
        self.expectPkt = 0
        # calculate the sequence space
        self.maxSequenceSpace = int(math.pow(2, sequence_bits))
        if windowSize is None:
            self.maxWindowSize = int(math.pow(2, sequence_bits-1))
        else:
            # check for exceding windowsize's upper limit
            if windowSize > int(math.pow(2, sequence_bits-1)):
                raise WindowSizeError("Invalid window size!")
            else:
                self.maxWindowSize = windowSize
        self.lastPkt = self.maxWindowSize - 1
        self.receiverWindow = OrderedDict()
        self.is_PktRec = False


    def checkSeqNumMatch(self, sequenceNumber):
        if sequenceNumber == self.expectPkt:
            return True
        return False

    def checkOrder(self, key):
        if self.expectPkt > self.lastPkt:
            if key < self.expectPkt and key > self.lastPkt:
                return True
        else:
            if key < self.expectPkt or key > self.lastPkt:
                return True
        return False

    def checkDup(self, key):
        if key in self.receiverWindow and self.receiverWindow[key] != None:
            return True
        return False

    def store(self, receivedPacket):
        if not self.checkSeqNumMatch(receivedPacket.SequenceNumber):
            sequenceNumber = self.expectPkt

            while sequenceNumber != receivedPacket.SequenceNumber:
                if sequenceNumber not in self.receiverWindow:
                    self.receiverWindow[sequenceNumber] = None

                sequenceNumber += 1
                if sequenceNumber >= self.maxSequenceSpace:
                    sequenceNumber %= self.maxSequenceSpace

        self.receiverWindow[receivedPacket.SequenceNumber] = receivedPacket

    def next(self):
        packet = None

        if len(self.receiverWindow) > 0:
            nextPkt = self.receiverWindow.items()[0]

            if nextPkt[1] != None:
                packet = nextPkt[1]

                del self.receiverWindow[nextPkt[0]]

                self.expectPkt = nextPkt[0] + 1
                if self.expectPkt >= self.maxSequenceSpace:
                    self.expectPkt %= self.maxSequenceSpace

                self.lastPkt = self.expectPkt + self.maxWindowSize - 1
                if self.lastPkt >= self.maxSequenceSpace:
                    self.lastPkt %= self.maxSequenceSpace
        return packet

    def set_is_PktRec(self):
        self.is_PktRec = True

class PacketHandler(Thread):
    """
    Thread for monitoring recieved pkt.
    """

    PACKET = namedtuple("Packet", ["SequenceNumber", "Checksum", "Data"])
    ACK = namedtuple("ACK", ["AckNumber", "Checksum"])

    def __init__(self, simulator, window, logger, timeout=10):
        Thread.__init__(self)
        self.simulator = simulator
        self.window = window
        self.logger = logger
        self.timeout = timeout


    def run(self):
        """
        Start monitoring packet receipt.
        """

        startReceive = False
        chance = 0
        while True:
            if not self.window.is_PktRec:
                self.window.set_is_PktRec()

            # Receive packet
            try:
                receivedPacket = self.simulator.u_receive()
            except socket.timeout:
                self.logger.info("receive time out {}...".format(startReceive))
                chance += 1
                if not startReceive or chance < 5:
                    continue
                else:
                    break
                #sys.exit()
            startReceive = True
            chance = 0

            # Parse header fields and payload data from the received packet
            receivedPacket = self.parse(receivedPacket)

            # Check whether the received packet is corrupted
            # Discard the packed if corrupted
            if self.isCorrupt(receivedPacket):
                continue

            # Check whether the reveived packet is in wrong order
            # Discard the packet if so
            if self.window.checkOrder(receivedPacket.SequenceNumber):

                # Use reliable data transfer to send ack
                self.rdt_send(receivedPacket.SequenceNumber)

                continue

            # Check whether the reveived packet is a duplicate
            # Discard the packet if so
            if self.window.checkDup(receivedPacket.SequenceNumber):
                continue

            # Otherwise, storing data in the window and send ack
            else:
                self.window.store(receivedPacket)
                self.rdt_send(receivedPacket.SequenceNumber)

            # If seq number mataches the expect pkt, then deliver to application layer
            if self.window.checkSeqNumMatch(receivedPacket.SequenceNumber):
                self.deliver_packets()

    def rdt_send(self, ackNumber):
        """
        Reliable data transfer for ack.
        """
        hashcode = hashlib.md5()
        hashcode.update(str(ackNumber))
        # hased_ackNum = hashcode.digest()

        ack = PacketHandler.ACK(AckNumber=ackNumber, Checksum=hashcode.digest())

        # Create a raw acknowledgement
        rawAck = self.make_pkt(ack)

        # Transmit an acknowledgement using underlying UDP protocol
        try:
            self.simulator.u_send(rawAck)
        except socket.timeout:
            self.logger.info("Could not send UDP packet")

    def parse(self, receivedPacket):
        """
        Parse header fields and payload data from the received packet.
        """
        header = receivedPacket[0:6]
        data = receivedPacket[6:]

        sequenceNumber = struct.unpack('=I', header[0:4])[0]
        checksum = struct.unpack('=H', header[4:])[0]

        packet = PacketHandler.PACKET(SequenceNumber=sequenceNumber, Checksum=checksum, Data=data)

        return packet

    def isCorrupt(self, receivedPacket):
        """
        Check whether the received packet is corrupted or not.
        """
        # Compute checksum for the received packet and compare with the received pkt

        data = receivedPacket.Data

        if (len(data) % 2) != 0:
            data += "0"

        sum = 0
        for i in range(0, len(data), 2):
            data16 = data[i] + ((data[i+1]) << 8)
            sum = self.carry_around_add(sum, data16)

        cur_Checksum = ~sum & 0xffff

        # cur_Checksum = self.checksum(receivedPacket.Data)
        if cur_Checksum != receivedPacket.Checksum:
            return True
        else:
            return False

    def carry_around_add(self, sum, data16):
        """
        Helper function for carry around add.
        """
        sum = sum + data16
        return (sum & 0xffff) + (sum >> 16)

    def make_pkt(self, ack):
        """
        Create a raw acknowledgement.
        """
        ackNumber = struct.pack('=I', ack.AckNumber)
        checksum = struct.pack('=16s', ack.Checksum)
        rawAck = bytearray()
        # rawAck = ackNumber + checksum
        rawAck[0:4] = ackNumber
        rawAck[4:20] = checksum
        return rawAck

    def deliver_packets(self):
        """
        Deliver packets to Application Layer.
        """
        while True:
            # Deliver pkt to Application Layer
            packet = self.window.next()

            if packet:
                data = packet.Data
                try:
                    sys.stdout.write(data)
                    sys.stdout.flush()
                except IOError as e:
                    self.logger.info("Could not write to file handler: {}".format(e))
                # self.deliver(packet.Data)
            else:
                break

if __name__ == "__main__":
    # test out BogoReceiver
    rcvr = MyReceiver()
    # rcvr = BogoReceiver()
    rcvr.receive()
