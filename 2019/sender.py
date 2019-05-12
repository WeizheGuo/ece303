# -*- coding: utf8 -*-
# Written by S. Mevawala, modified by D. Gitzel

# Thanks for Siri for helping me on the multi-thread idea and implementation here!

import logging
import socket

import channelsimulator
import utils
import sys
import struct
import math
import os
import time
import hashlib
import random
from collections import namedtuple
from collections import OrderedDict
from threading import Thread
from threading import Lock

class Sender(object):

    # def __init__(self, inbound_port=50006, outbound_port=50005, timeout=10, debug_level=logging.INFO):
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

# Lock for synchronized access to 'Window' class
LOCK = Lock()

class MySender(BogoSender):
    def __init__(self):
        super(MySender, self).__init__()
        self.sequenceNumberBits = 30
        self.maxSegmentSize = 1024
        self.timeout = 0.3
        self.windowSize = 16

    def send(self, data):
        self.logger.info("Sending on port: {} and waiting for ACK on port: {}".format(self.outbound_port, self.inbound_port))
        # Create an object of 'Window', which handles packet transmission
        window = Window(self.sequenceNumberBits, self.windowSize)

        # self.logger.info("Creating a thread to monitor packet transmission")
        packetHandler = PacketHandler(self.simulator, data, window, self.logger, self.maxSegmentSize, self.timeout)
        # Create a thread named 'ACKHandler' to monitor acknowledgement receipt
        ackHandler = ACKHandler(self.simulator, window, self.logger)

        packetHandler.start()
        ackHandler.start()

        packetHandler.join()
        ackHandler.join()


class Window(object):
    """
    Class for assisting packet transmission.
    """

    def __init__(self, sequenceNumberBits, windowSize=None):
        self.expectAck = 0
        self.next_Seq_Num = 0
        self.nextPkt = 0
        self.max_Seq_Space = int(math.pow(2, sequenceNumberBits))
        if windowSize is None:
            self.maxWindowSize = int(math.pow(2, sequenceNumberBits-1))
        else:
            if windowSize > int(math.pow(2, sequenceNumberBits-1)):
                raise WindowSizeError("Invalid window size!!")
            else:
                self.maxWindowSize = windowSize
        self.transmissionWindow = OrderedDict()
        self.isPacketTransmission = True

    def checkEmpty(self):
        if len(self.transmissionWindow) == 0:
            return True
        return False

    def checkFull(self):
        if len(self.transmissionWindow) >= self.maxWindowSize:
            return True
        return False

    def checkDup(self, key):
        if key in self.transmissionWindow:
            return True
        return False

    def next(self):
        return self.nextPkt

    def slideWindow(self, key):
        with LOCK:
            self.transmissionWindow[key] = [None, False]

            self.next_Seq_Num += 1
            if self.next_Seq_Num >= self.max_Seq_Space:
                self.next_Seq_Num %= self.max_Seq_Space

            self.nextPkt += 1

    def start(self, key):
        with LOCK:
            self.transmissionWindow[key] = [time.time(), False]

    def restart(self, key):
        with LOCK:
            self.transmissionWindow[key] = [time.time(), False]

    def stop(self, key):
        if self.checkDup(key):
            self.transmissionWindow[key][0] = None

        if key == self.expectAck:
            for k, v in self.transmissionWindow.items():
                if v[0] == None and v[1] == True:
                    del self.transmissionWindow[k]
                else:
                    break

            if len(self.transmissionWindow) == 0:
                self.expectAck = self.next_Seq_Num
            else:
                self.expectAck = self.transmissionWindow.items()[0][0]

    def start_time(self, key):
        return self.transmissionWindow[key][0]

    def unacked(self, key):
        if (self.checkDup(key) and self.transmissionWindow[key][1] == False):
            return True
        return False

    def mark_acked(self, key):
        with LOCK:
            if self.checkDup(key):
                self.transmissionWindow[key][1] = True

    def stop_transmission(self):
        with LOCK:
            self.isPacketTransmission = False

    def transmit(self):
        return self.isPacketTransmission

class PacketHandler(Thread):
    """
    Thread for monitoring packet transmission.
    """

    HEADER_LENGTH = 6
    PACKET = namedtuple("Packet", ["SequenceNumber", "Checksum", "Data"])

    def __init__(self, simulator, data, window, logger, maxSegmentSize=1024, timeout=10, threadName="PacketHandler"):
        Thread.__init__(self)
        self.simulator = simulator
        self.data = data
        self.window = window
        self.logger = logger
        self.maxSegmentSize = maxSegmentSize
        self.maxPayloadSize = maxSegmentSize - PacketHandler.HEADER_LENGTH
        self.timeout = timeout
        self.threadName = threadName

    def run(self):
        """
        Start packet transmission.
        """

        self.logger.info("[{}] Generating packets".format(self.threadName))
        packets = self.make_Packets()

        self.logger.info("[{}] Starting packet transmission".format(self.threadName))
        while (not self.window.checkEmpty() or
                self.window.next() < self.totalPackets):
            # If window is checkFull, then don't transmit a new packet
            if self.window.checkFull():
                pass
            # If window is not checkFull, but all packets are transmitted already, then stop packet transmission
            elif (not self.window.checkFull() and
                    self.window.next() >= self.totalPackets):
                pass

            # Using underlying UDP protocol
            else:
                # Receive packet from Application Layer
                packet = packets[self.window.next()]

                # Slide transmission window by 1
                self.window.slideWindow(packet.SequenceNumber)

                # Create a new thread
                threadName = "Packet(" + str(packet.SequenceNumber) + ")"
                singlePacket = SinglePacket(self.simulator, self.window, packet, self.logger, self.timeout, threadName=threadName)

                # Start thread execution
                singlePacket.start()

        # Stop packet transmission
        self.logger.info("[{}] Stopping packet transmission".format(self.threadName))
        self.window.stop_transmission()

    def make_Packets(self):
        """
        make packets for transmission
        """

        packets = []
        num_bytes = len(self.data)
        extra = 1 if num_bytes % self.maxPayloadSize else 0

        for i in xrange(num_bytes / self.maxPayloadSize + extra):
            d = self.data[i * self.maxPayloadSize: (i+1)*self.maxPayloadSize]
            sequenceNumber = i % self.window.max_Seq_Space

            # Create a packet with the format designed
            pkt = PacketHandler.PACKET(SequenceNumber=sequenceNumber, Checksum=self.checksum(d), Data=d)

            packets.append(pkt)

        self.totalPackets = len(packets)

        return packets[:self.totalPackets]

    def checksum(self, data):
        """
        Compute and return a checksum of the given payload data.
        """
        # Force data into 16 bit chunks
        if (len(data) % 2) != 0:
            data += "0"

        sum = 0
        for i in range(0, len(data), 2):
            data16 = data[i] + ((data[i+1]) << 8)
            sum = self.carry_around_add(sum, data16)

        return ~sum & 0xffff

    def carry_around_add(self, sum, data16):
        """
        Helper function for carry around add.
        """
        sum = sum + data16
        return (sum & 0xffff) + (sum >> 16)

class SinglePacket(Thread):
    """
    Thread for monitoring transmission of single packet.
    """

    def __init__(self, simulator, window, packet, logger, timeout=10, threadName="Packet(?)"):
        Thread.__init__(self)
        self.simulator = simulator
        self.window = window
        self.packet = packet
        self.logger = logger
        self.timeout = timeout
        self.threadName = threadName

    def run(self):
        """
        Monitoring transmission of single packet.
        """
        # Transmit a packet using  UDP protocol and start the corresponding timer.
        self.rdt_send(self.packet)
        self.window.start(self.packet.SequenceNumber)

        # Keep track of the pkt if not acked
        while self.window.unacked(self.packet.SequenceNumber):
            timeLapsed = (time.time() - self.window.start_time(self.packet.SequenceNumber))

            # Retransmit packet and reset the timer if time out.
            if timeLapsed > self.timeout:
                self.rdt_send(self.packet)
                self.window.restart(self.packet.SequenceNumber)

        # Stop tracking the pkt as it is acked
        with LOCK:
            self.window.stop(self.packet.SequenceNumber)

    def rdt_send(self, packet):
        """
        Reliable data transfer (similar to the one in the receiver).
        """
        # Create a raw packet
        sequenceNumber = struct.pack('=I', packet.SequenceNumber)
        checksum = struct.pack('=H', packet.Checksum)
        rawPacket = sequenceNumber + checksum + packet.Data
    
        # self.udt_send(rawPacket)
        try:
            with LOCK:
                self.simulator.u_send(bytearray(rawPacket))  # send data
        except socket.timeout:
            self.logger.info(format(self.threadName, e))
            pass

class ACKHandler(Thread):
    """
    Thread for handling received ack.
    """

    ACK = namedtuple("ACK", ["AckNumber", "Checksum"])

    def __init__(self, simulator, window, logger, threadName="ACKHandler"):
        Thread.__init__(self)
        self.simulator = simulator
        self.window = window
        self.threadName = threadName
        self.logger = logger

    def run(self):

        while self.window.transmit():
            # hold on if all the packets transmitted are acked and exist pkts waiting for transmission
            if self.window.checkEmpty():
                continue

            # Receive acknowledgement
            try:
                receivedAck = self.simulator.u_receive()
                receivedAck = self.parse(receivedAck)
            except socket.timeout:
                self.logger.info("[{}] Could not receive UDP packet".format(self.threadName))
                continue
            except Exception as e:
                self.logger.info("parse receive ack error:{}".format(e))
                continue

            # Check for corruption
            if self.Iscorrupt(receivedAck):
                continue

            # If beyong the range, discard the ack
            if not self.window.checkDup(receivedAck.AckNumber):
                continue

            # Mark transmitted packet as acked
            self.window.mark_acked(receivedAck.AckNumber)

    def parse(self, receivedAck):
        """
        Parse header fields from the received acknowledgement.
        """
        ackNumber = struct.unpack('=I', receivedAck[0:4])[0]
        checksum = struct.unpack('=16s', receivedAck[4:20])[0]

        ack = ACKHandler.ACK(AckNumber=ackNumber,
                             Checksum=checksum)

        return ack

    def Iscorrupt(self, receivedAck):
        """
        Check whether the received acknowledgement is corrupted.
        """
        # Compute hash code for the received acknowledgement
        hashcode = hashlib.md5()
        hashcode.update(str(receivedAck.AckNumber))

        # Compare computed hash code with the checksum of received acknowledgement
        if hashcode.digest() != receivedAck.Checksum:
            return True
        else:
            return False

if __name__ == "__main__":
    # test out BogoSender
    DATA = bytearray(sys.stdin.read())
    sndr = MySender()
    # sndr = BogoSender()
    sndr.send(DATA)
