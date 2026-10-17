import argparse
from pathlib import Path
from .data import generate_demo
from .pipeline import run

def main():
    parser=argparse.ArgumentParser(description='Supply-chain planning experiments')
    sub=parser.add_subparsers(dest='command',required=True)
    demo=sub.add_parser('demo',help='Generate independent synthetic data and run all three experiments')
    demo.add_argument('--data-dir',default='data/demo');demo.add_argument('--output',default='reports/demo')
    demo.add_argument('--seed',type=int,default=20261017)
    local=sub.add_parser('evaluate',help='Evaluate normalized private data; output must be outside the repository')
    local.add_argument('--data-dir',required=True);local.add_argument('--output',required=True)
    args=parser.parse_args()
    if args.command=='demo':
        generate_demo(args.data_dir,seed=args.seed)
        result=run(args.data_dir,args.output,mode='independent_synthetic')
    else: result=run(args.data_dir,args.output)
    print(f"Completed {result['data_mode']}: {result['daily']['skus']} daily SKUs, "
          f"{result['annual']['cohorts']} annual cohorts. Results: {Path(args.output).resolve()}")

if __name__=='__main__':main()
