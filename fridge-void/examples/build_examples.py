#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the fridge-void example ledger and report snapshots.

The demo ledger is one person's 12 weeks of grocery outcomes (2026-06-01
to 2026-08-24): 62 batches, a 24% waste rate, two oat-milk attempts that
both ended in the bin, a 66% leafy-green disaster zone, one prawn
tragedy, and a pantry with a pumpkin past its DUE line.

  python3 build_examples.py            # write ledger/cart + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "fridge_void.py")

LEDGER = """\
bought	name	category	qty	unit	cost	outcome	outcome_date	cause
2026-06-01	菠菜	绿叶菜	400	g	6.5	tossed	2026-06-06	forgot
2026-06-01	鸡蛋	蛋奶	750	g	21.0	ate	2026-06-14	
2026-06-01	番茄	茄果	600	g	9.0	ate	2026-06-08	
2026-06-03	燕麦奶	乳品	1000	ml	28.0	tossed	2026-06-17	rejected
2026-06-03	鸡胸肉	肉禽	500	g	14.0	ate	2026-06-06	
2026-06-05	生菜	绿叶菜	400	g	5.0	tossed	2026-06-10	spoiled
2026-06-05	土豆	根茎	1000	g	7.0	ate	2026-06-20	
2026-06-05	番茄	茄果	600	g	9.5	ate	2026-06-09	
2026-06-07	米饭	主食	800	g	4.0	tossed	2026-06-09	leftover
2026-06-07	五花肉	肉禽	600	g	29.4	ate	2026-06-11	
2026-06-08	苹果	水果	1000	g	15.8	ate	2026-06-16	
2026-06-08	苋菜	绿叶菜	300	g	4.5	tossed	2026-06-13	forgot
2026-06-09	香蕉	水果	900	g	10.8	ate	2026-06-15	
2026-06-10	酸奶	蛋奶	900	ml	18.0	tossed	2026-06-24	expired
2026-06-12	鲈鱼	水产	500	g	32.0	gave	2026-06-15	
2026-06-15	青菜	绿叶菜	400	g	5.0	ate	2026-06-19	
2026-06-15	香蕉	水果	1000	g	12.0	ate	2026-06-22	
2026-06-16	茄子	茄果	500	g	6.0	ate	2026-06-21	
2026-06-18	羽衣甘蓝	绿叶菜	200	g	9.9	tossed	2026-06-25	rejected
2026-06-19	鸡腿	肉禽	600	g	13.2	ate	2026-06-24	
2026-06-20	黄瓜	茄果	600	g	7.2	ate	2026-06-26	
2026-06-22	牛奶	蛋奶	2000	ml	26.0	ate	2026-07-02	
2026-07-01	西瓜	水果	4000	g	20.0	tossed	2026-07-09	spoiled
2026-07-01	排骨	肉禽	800	g	47.2	ate	2026-07-05	
2026-07-03	胡萝卜	根茎	500	g	4.5	tossed	2026-07-28	forgot
2026-07-03	基围虾	水产	600	g	45.0	tossed	2026-07-08	spoiled
2026-07-05	生菜	绿叶菜	400	g	5.5	ate	2026-07-09	
2026-07-06	猪肝	肉禽	300	g	13.5	ate	2026-07-09	
2026-07-08	鸡胸肉	肉禽	700	g	19.6	ate	2026-07-14	
2026-07-08	番茄	茄果	600	g	9.0	ate	2026-07-14	
2026-07-09	油麦菜	绿叶菜	400	g	6.0	tossed	2026-07-14	forgot
2026-07-10	豆腐	豆制品	400	g	5.0	ate	2026-07-13	
2026-07-12	桃子	水果	1200	g	18.0	ate	2026-07-20	
2026-07-12	土豆	根茎	800	g	5.6	ate	2026-07-20	
2026-07-15	青菜	绿叶菜	400	g	5.5	ate	2026-07-18	
2026-07-15	番茄	茄果	800	g	12.0	ate	2026-07-22	
2026-07-16	豆腐	豆制品	800	g	9.0	ate	2026-07-20	
2026-07-20	牛肉	肉禽	500	g	39.5	ate	2026-07-25	
2026-07-22	燕麦奶	乳品	1000	ml	28.0	tossed	2026-08-05	rejected
2026-07-24	桃子	水果	1000	g	14.0	ate	2026-07-30	
2026-07-25	黄瓜	茄果	600	g	7.5	ate	2026-07-30	
2026-07-28	鸡蛋	蛋奶	750	g	21.9	ate	2026-08-06	
2026-08-01	生菜	绿叶菜	400	g	5.5	tossed	2026-08-07	spoiled
2026-08-01	带鱼	水产	600	g	36.0	ate	2026-08-04	
2026-08-03	苦瓜	茄果	500	g	6.5	ate	2026-08-07	
2026-08-03	猪肉糜	肉禽	400	g	15.2	ate	2026-08-09	
2026-08-05	冬瓜	茄果	2000	g	8.0	open		
2026-08-06	鲈鱼	水产	500	g	30.0	ate	2026-08-10	
2026-08-08	空心菜	绿叶菜	400	g	5.0	tossed	2026-08-12	spoiled
2026-08-08	葡萄	水果	1000	g	19.9	ate	2026-08-15	
2026-08-10	米饭	主食	500	g	2.5	tossed	2026-08-12	leftover
2026-08-10	猪肉糜	肉禽	400	g	15.2	ate	2026-08-14	
2026-08-12	南瓜	茄果	1500	g	11.7	open		
2026-08-12	鸡胸肉	肉禽	600	g	16.8	ate	2026-08-18	
2026-08-14	青菜	绿叶菜	400	g	5.5	ate	2026-08-17	
2026-08-14	毛豆	豆制品	600	g	7.2	ate	2026-08-19	
2026-08-17	番茄	茄果	700	g	9.8	ate	2026-08-21	
2026-08-18	鸡蛋	蛋奶	750	g	21.9	open		
2026-08-20	豆腐	豆制品	400	g	5.0	open		
2026-08-21	米饭	主食	400	g	2.0	ate	2026-08-23	
2026-08-23	香蕉	水果	800	g	9.6	open		
2026-08-24	牛奶	蛋奶	1000	ml	13.0	open		
"""

CART = """\
name	category	qty	unit	cost				
燕麦奶	乳品	1000	ml	28.0				
菠菜	绿叶菜	400	g	6.5				
鸡腿	肉禽	600	g	13.2				
"""

SNAPSHOTS = [
    (["ledger", "ledger.tsv"], "sample-ledger.txt"),
    (["board", "ledger.tsv"], "sample-board.txt"),
    (["cause", "ledger.tsv"], "sample-cause.txt"),
    (["tax", "ledger.tsv"], "sample-tax.txt"),
    (["pantry", "ledger.tsv"], "sample-pantry.txt"),
    (["item", "ledger.tsv", "燕麦奶"], "sample-item.txt"),
    (["plan", "ledger.tsv", "cart.tsv"], "sample-plan.txt"),
]


def resolve(arg):
    """File-name args refer to files in HERE; resolve them absolutely so the
    command works from any working directory (CI runs from the repo root)."""
    path = os.path.join(HERE, arg)
    return path if os.path.exists(path) else arg


def main():
    check = "--check" in sys.argv
    ledger_path = os.path.join(HERE, "ledger.tsv")
    cart_path = os.path.join(HERE, "cart.tsv")

    if check:
        for path, text in ((ledger_path, LEDGER), (cart_path, CART)):
            with open(path, "r", encoding="utf-8") as fh:
                if fh.read() != text:
                    print("MISMATCH: %s differs from build_examples.py" % path)
                    return 1
    else:
        with open(ledger_path, "w", encoding="utf-8") as fh:
            fh.write(LEDGER)
        with open(cart_path, "w", encoding="utf-8") as fh:
            fh.write(CART)

    status = 0
    for args, name in SNAPSHOTS:
        path = os.path.join(HERE, name)
        proc = subprocess.run([sys.executable, CLI] + [resolve(a) for a in args],
                              capture_output=True, text=True)
        out = proc.stdout
        if proc.returncode not in (0, 4):
            print("CLI %s failed: %s" % (args, proc.stderr))
            return 1
        if check:
            with open(path, "r", encoding="utf-8") as fh:
                if fh.read() != out:
                    print("MISMATCH: %s is stale (regenerate snapshots)" % name)
                    status = 1
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(out)
            print("wrote %s (exit %d)" % (name, proc.returncode))
    return status


if __name__ == "__main__":
    sys.exit(main())
