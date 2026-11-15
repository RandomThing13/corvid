"""Create a mode-0600 ignored allowlisted secret file; never print credentials."""
import argparse,os
from pathlib import Path
from dotenv import dotenv_values
from deployment.gates import require_final

def main():
 p=argparse.ArgumentParser();p.add_argument('--ledger-verified',action='store_true',required=True);p.add_argument('--local-paid-disabled',action='store_true',required=True);a=p.parse_args()
 root=Path(__file__).resolve().parents[1];require_final(root)
 original=dotenv_values(root/'.env')
 if original.get('STOA_ENABLE_PAID_API')!='0':raise RuntimeError('Local paid flag is still enabled')
 key=original.get('OPENAI_API_KEY')
 if not key or original.get('STOA_API_BALANCE_VERIFIED')!='1':raise RuntimeError('Existing access configuration is not verified')
 if '\n' in key or '\r' in key:raise RuntimeError('Invalid key format')
 dest=root/'deployment/.env.modal-secret'
 fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:f.write('OPENAI_API_KEY='+key+'\nSTOA_ENABLE_PAID_API=1\nSTOA_API_BALANCE_VERIFIED=1\n')
 print('Created ignored scoped secret file; contents not displayed.')
if __name__=='__main__':main()
