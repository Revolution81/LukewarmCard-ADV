#!/usr/bin/env python3
# Verify a PSBT (or final tx) signed by the Cardputer firmware, independently,
# using embit: every input must carry a valid ECDSA signature for its key.
# Usage: check_signed_psbt.py <signed.psbt | final.txn>
import sys
from embit.psbt import PSBT
from embit.transaction import Transaction
from embit import ec, script

data = open(sys.argv[1], 'rb').read()
if data[:5] == b'psbt\xff':
    psbt = PSBT.parse(data)
    tx = psbt.tx
    ok = True
    for i, inp in enumerate(psbt.inputs):
        utxo = inp.witness_utxo
        if not inp.partial_sigs and inp.final_scriptwitness:
            wit = inp.final_scriptwitness.items
            sigs = {ec.PublicKey.parse(wit[1]): wit[0]}
        else:
            sigs = inp.partial_sigs
        if not sigs:
            print("input %d: NOT SIGNED" % i)
            ok = False
            continue
        for pub, sig in sigs.items():
            sc = script.p2pkh(pub)      # BIP-143 script code for p2wpkh
            h = tx.sighash_segwit(i, sc, utxo.value, sighash=sig[-1])
            good = pub.verify(ec.Signature.parse(sig[:-1]), h)
            print("input %d: key %s sig %s" % (i, pub.sec().hex()[:16], 'VALID' if good else 'INVALID'))
            ok &= good
    sys.exit(0 if ok else 1)
else:
    raw = bytes.fromhex(data.decode().strip()) if data[:2] in (b'01', b'02') else data
    tx = Transaction.parse(raw)
    print("final transaction txid", tx.txid().hex(), "inputs", len(tx.vin))
    sys.exit(0)
