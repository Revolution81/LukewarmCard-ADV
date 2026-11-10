#!/usr/bin/env python3
# Build a mainnet BIP-84 PSBT for the BIP-39 test mnemonic "abandon x11 about"
# (fingerprint 73c5da0a), spending a made-up UTXO. Used to check that the
# Cardputer firmware signs correctly; verify with check_signed_psbt.py.
#
# Usage: make_test_psbt.py <out.psbt>
import sys, hashlib
from embit import bip39, bip32, script
from embit.psbt import PSBT, InputScope, OutputScope, DerivationPath
from embit.transaction import Transaction, TransactionInput, TransactionOutput

MNEMONIC = "abandon " * 11 + "about"
seed = bip39.mnemonic_to_seed(MNEMONIC)
root = bip32.HDKey.from_seed(seed)
fp = root.my_fingerprint

def key_at(path):
    return root.derive(path)

def deriv(path):
    return DerivationPath(fp, bip32.parse_path(path))

in_path = "m/84h/0h/0h/0/0"
chg_path = "m/84h/0h/0h/1/0"
k_in, k_chg = key_at(in_path), key_at(chg_path)
spk_in = script.p2wpkh(k_in.key)
spk_chg = script.p2wpkh(k_chg.key)

# made-up previous transaction paying 100,000 sats to our first address
prev = Transaction(vin=[TransactionInput(bytes(32), 0)],
                   vout=[TransactionOutput(100_000, spk_in)])
prev_txid = prev.txid()

dest = script.p2wpkh(bip32.HDKey.from_seed(hashlib.sha256(b'dest').digest()).key)
tx = Transaction(vin=[TransactionInput(prev_txid, 0, sequence=0xfffffffd)],
                 vout=[TransactionOutput(60_000, dest), TransactionOutput(39_000, spk_chg)])

psbt = PSBT(tx)
psbt.inputs[0].witness_utxo = prev.vout[0]
psbt.inputs[0].non_witness_utxo = prev
psbt.inputs[0].bip32_derivations[k_in.key.get_public_key()] = deriv(in_path)
psbt.outputs[1].bip32_derivations[k_chg.key.get_public_key()] = deriv(chg_path)

open(sys.argv[1], 'wb').write(psbt.serialize())
print("wrote", sys.argv[1], "fingerprint", fp.hex(), "input addr", script.p2wpkh(k_in.key).address())
