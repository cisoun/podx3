#!/usr/bin/env python

"""
Simple POD x3 control utility, written to test pod functionality.
Warning: this code may remove your warranty, erase firmware, eat your dog and
so on. Use at your own risk.
pyusb is required.
This code is released under GPL v2. Have fun.

NOTE:
    before using, look at the end of the file and uncomment functon calls you
    want to use

USAGE:
    1) turn on pod
    2) look at the end of this file and comment/uncomment function calls you
       want to test
    2.1) it sometimes doesn't work for the first time, works for the second and
       then doesn't work until pod is turned off and on again.
    3) you'll see configuration packets coming as you play with x3 controls

    You can get interactive console: run it using
    python -i pypodx3.py then you can control pod object...

"""

import sys, time, math, array, struct, string
import struct
import threading
import signal
import io
import traceback
from pypodx3_parser import PacketParser, PacketCompleter


def formathex(buffer):
    """ return buffer content as hex formatted bytes """
    buf2 = []
    if not isinstance(buffer, array.array):
        return "== " + str(buffer)
    for item in buffer:
        buf2.append("%02X" % (item))
    return " ".join(buf2)


def read_file(path):
    with open(path, 'r') as f:
        return f.readline()


class POD:
    VENDOR_ID     = 0x0E41   #: Vendor Id
    PRODUCT_ID    = 0x414A   #: Product Id for POD X3 bean
    INTERFACE_ID  = 1        #: The interface we use to talk to the device
    BULK_IN_EP    = 0x81     #: Endpoint for Bulk reads
    BULK_OUT_EP   = 0x01     #: Endpoint for Bulk writes
    PACKET_LENGTH = 0x40     #: 64 bytes

    L6_X3_CTRL = 0x67 # bRequest == 103
    USB_VENDOR_H2D = 0x40
    USB_VENDOR_D2H = 0xC0

    def __init__(self,) :
        self.useKernelDriver = False
        for i in range(0, 9):
            self.hwdepDevice = "hwC%dD0" % i
            try:
                path = "/sys/class/sound/%s/device/id" % self.hwdepDevice
                if read_file(path) == "PODX3\n":
                    self.hwdep = io.FileIO(
                        "/dev/snd/" + self.hwdepDevice, "rb+")
                    self.useKernelDriver = True
                    return
            except FileNotFoundError:
                pass
            except Exception as e:
                traceback.print_exc()
                pass

        import usb.util, usb.core
        self.device = usb.core.find(
            idVendor=POD.VENDOR_ID,
            idProduct=POD.PRODUCT_ID)

        if not self.device:
            sys.exit("not device found")
        if self.device.is_kernel_driver_active(0):
            try:
                self.device.detach_kernel_driver(0)
                print("kernel driver detached")
            except usb.core.USBError as e:
                sys.exit("Could not detach kernel driver: %s" % e)
        else:
            print("no kernel driver attached")

    def set_guitar_mic(self):
        """ set guitar/mic mode """
        try:
            print("g/m:start bulk write")
            buf = [0x18, 0x00, 0x01, 0x00, 0x05, 0x00, 0x0A, 0x40, 0x01, 0x03,
                   0x00, 0x16, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                   0x16, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00]
            sent = self.device.write(POD.BULK_OUT_EP, buf)
        except Exception as e:
            print("exception in bulk write:")
            print(e)

    def read_data(self, dataLen, addr):
        resp = self.device.ctrl_transfer(
            POD.USB_VENDOR_H2D,
            POD.L6_X3_CTRL,
            wValue=(dataLen << 8) | 0x21,
            wIndex=addr, data_or_wLength=0)
        #print("resp (ACK)", formathex(resp))
        resp = self.device.ctrl_transfer(
            POD.USB_VENDOR_D2H,
            POD.L6_X3_CTRL,
            wValue=0x12,
            wIndex=0x00,
            data_or_wLength=1)
        #print("resp (x12)", formathex(resp))
        resp = self.device.ctrl_transfer(
            POD.USB_VENDOR_D2H,
            POD.L6_X3_CTRL,
            wValue=0x13,
            wIndex=0x00,
            data_or_wLength=dataLen)
        #print("resp (x13)", formathex(resp))
        return resp

    def init(self):
        """Initialize device."""
        if self.useKernelDriver:
            return

        # POD initialization
        # Tying to do the same things the original driver does during X3
        # startup.
        print("set configuration...")
        cfg = self.device.set_configuration(1)
        print("-- init (expecting 20 10 04)")
        resp = self.device.ctrl_transfer(
            POD.USB_VENDOR_D2H,
            POD.L6_X3_CTRL,
            wValue=0x11,
            wIndex=0x00,
            data_or_wLength=3)
        print("resp: %s" % formathex(resp))

        print("-- INIT F000...F080")
        #a sequence i don;t understand yet
        bytes = [0x00, 0x08, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38, 0x40, 0x48,
                 0x50, 0x58, 0x60, 0x68, 0x70, 0x78, 0x80]
        for item in bytes:
            # This looks exactly like $linuxdrv/driver.c/line6_read_data()
            d = self.read_data(8, 0xF000 | item)
            print(formathex(d))
            resp = self.device.ctrl_transfer(
                POD.USB_VENDOR_H2D,
                POD.L6_X3_CTRL,
                wValue=0x0201,
                wIndex=0x02,
                data_or_wLength=0)
            # print("resp (x201)", formathex(resp))

        # TODO: not needed?
        #print("wake up")
        #resp = self.device.ctrl_transfer(0x00, usb.REQ_SET_FEATURE, wValue=0x01, wIndex=0x00, data_or_wLength=0)

    def set_param(self, paramnum, value_percent):
        """Set channel parameter value.

        Most , if not all, values are in range 0x00 00 00 00 - 0x3f 80 00 00.
        """
        buf = [0x1C, 0x00, 0x01, 0x00, 0x06, 0x00, 0x0A, 0x40, 0x01, 0x03,
               0x00, 0x15, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03, 0x00,
               0x01, 0x00, 0x00, 0x00, 0x05, 0x00, 0x10, 0x3F, 0x00, 0x00,
               0x00, 0x00]
        maxval = 0x3f800000
        val = (maxval/100) * value_percent
        try:
            buf[0x18] = paramnum
            paramval = struct.pack('i', val)
            buf[0x1c] = ord(paramval[0])
            buf[0x1d] = ord(paramval[1])
            buf[0x1e] = ord(paramval[2])
            buf[0x1f] = ord(paramval[3])
            print('val=',paramval, 'paramnum=', paramnum)
            print(formathex(buf))
            print("start bulk write")
            sent = self.device.write(POD.BULK_OUT_EP, buf, 100)
            print("past write", sent)
            #sent = self.device.write(POD.BULK_OUT_EP, buf, 100)
            #print("past write2", sent)
            #this message can be see in usb dumps everythime after changing param value,
            #however it appears only once after cranking param up and down constantly
            resp = self.device.ctrl_transfer(
                POD.USB_VENDOR_D2H,
                POD.L6_X3_CTRL,
                wValue=0x11,
                wIndex=0x00,
                data_or_wLength=3)
            print("resp", resp)
        except Exception as e:
            print("exception in bulk write:",e)

    def get_serial_number(self):
        if self.useKernelDriver:
            serial = read_file("/sys/class/sound/%s/device/podhd/serial_number"
                % self.hwdepDevice)
            print("POD Serial: " + serial)
        else:
            d = self.read_data(4, 0x80d0)
            print("POD Serial: %d" % (struct.unpack('<I', d.tobytes())))

    def read(self):
        if self.useKernelDriver:
            return self.hwdep.read(1024)
        return self.device.read(POD.BULK_IN_EP, 0x40)

    def write(self, data):
        if self.useKernelDriver:
            self.hwdep.write(data)
        else:
            raise "unimplemented"


pod = POD()

# NOTE: init not needed for the bulk stuff to work
pod.init()
pod.get_serial_number()

pc = PacketCompleter(PacketParser())
pc.start()

run = True
def signal_handler(signal, frame):
    global run
    run = False
    sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)

#pod.set_param(5, 10)
#pod.set_guitar_mic()

if False:
    # blink the delay button
    # TODO: the binary stuff should be generated by the classes in the parser module
    # pod.write(''.join(map(chr, [20, 0, 1, 0, 4, 0, 10, 64, 0, 3, 0, 19, 0, 0, 0, 0, 4, 0, 5, 0, 0, 0, 0, 0])))
    # time.sleep(0.3)
    # pod.write(''.join(map(chr, [20, 0, 1, 0, 4, 0, 10, 64, 0, 3, 0, 19, 0, 0, 0, 0, 4, 0, 5, 0, 1, 0, 0, 0])))
    # time.sleep(0.3)
    # pod.write(''.join(map(chr, [20, 0, 1, 0, 4, 0, 10, 64, 0, 3, 0, 19, 0, 0, 0, 0, 4, 0, 5, 0, 0, 0, 0, 0])))
    # time.sleep(0.3)
    # pod.write(''.join(map(chr, [20, 0, 1, 0, 4, 0, 10, 64, 0, 3, 0, 19, 0, 0, 0, 0, 4, 0, 5, 0, 1, 0, 0, 0])))
    pod.write(bytes([20, 0, 1, 0, 4, 0, 10, 64, 0, 3, 0, 19, 0, 0, 0, 0, 4, 0, 5, 0, 0, 0, 0, 0]))
    time.sleep(1)
    pod.write(bytes([20, 0, 1, 0, 4, 0, 10, 64, 0, 3, 0, 19, 0, 0, 0, 0, 4, 0, 5, 0, 1, 0, 0, 0]))
    time.sleep(1)
    pod.write(bytes([20, 0, 1, 0, 4, 0, 10, 64, 0, 3, 0, 19, 0, 0, 0, 0, 4, 0, 5, 0, 0, 0, 0, 0]))
    time.sleep(1)
    pod.write(bytes([20, 0, 1, 0, 4, 0, 10, 64, 0, 3, 0, 19, 0, 0, 0, 0, 4, 0, 5, 0, 1, 0, 0, 0]))

while run:
    try:
        resp = pod.read()
        pc.appendData(resp)
    except:
        traceback.print_exc()
        pass

pc.stop = True
time.sleep(1)
