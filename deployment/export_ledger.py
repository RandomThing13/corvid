"""Run ONLY after P04 complete and the local paid server has stopped."""
import argparse,json,os
from pathlib import Path
from deployment.gates import require_final
from deployment.ledger import export_spend
from dotenv import dotenv_values

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--local-paid-disabled',action='store_true',required=True)
    args=p.parse_args();root=Path(__file__).resolve().parents[1];require_final(root)
    # Operator must stop paid traffic first. This tool never changes the source DB.
    dest=root/'deployment/.env.ledger-transfer.json'
    if dotenv_values(root/'.env').get('STOA_ENABLE_PAID_API')!='0':raise RuntimeError('Local paid flag must be disabled by P04 owner first')
    data=export_spend(args.db)
    fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(data,f,sort_keys=True,allow_nan=False)
    print(json.dumps({'file':str(dest),'rows':len(data['rows']),'totals':data['totals']}))
if __name__=='__main__':main()
