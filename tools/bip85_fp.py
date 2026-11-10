#!/usr/bin/env python3
# Independent check for the duress-PIN test: fingerprint of the BIP-85
# 12-word child (given index) of the "abandon x11 about" test seed, via embit.
#   bip85_fp.py 2001   -> F00F1FC0
import sys
from embit import bip39, bip32, bip85
root = bip32.HDKey.from_seed(bip39.mnemonic_to_seed("abandon " * 11 + "about"))
child = bip85.derive_mnemonic(root, num_words=12, index=int(sys.argv[1]))
print(bip32.HDKey.from_seed(bip39.mnemonic_to_seed(child)).my_fingerprint.hex().upper())
