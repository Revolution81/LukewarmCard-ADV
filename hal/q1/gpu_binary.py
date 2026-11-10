# gpu_binary.py - Cardputer port: the Q's GPU co-processor firmware image is
# not used here (there's no GPU chip). Debug Functions > BBQr Demo shows this
# module's data as animated QR codes, so give it some test data instead.
VERSION = 'none (Cardputer)'
BINARY = bytes(range(256)) * 8          # 2K of sample data (RAM is tight)
