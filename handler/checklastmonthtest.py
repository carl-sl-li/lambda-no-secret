from datetime import date, timedelta
from decimal import Decimal
import os
import json
import boto3
import hvac

print("Loading function")

today = date.today()
firstofmonth = today.replace(day=1)
lastmonth = firstofmonth - timedelta(days=1)
startdate = lastmonth.strftime('%Y-%m')+'-01'
enddate = today.strftime('%Y-%m')+'-01'

def get_aws_creds(path):
    vault_client = hvac.Client(url=os.environ['VAULTURL'])
    vault_client.auth.aws.iam_login(os.environ['AWS_ACCESS_KEY_ID'], os.environ['AWS_SECRET_ACCESS_KEY'], os.environ['AWS_SESSION_TOKEN'])
    response = vault_client.secrets.aws.generate_credentials(
        name=path.split('/')[-1],
        mount_point=path.rsplit('/', 2)[0],
        ttl=900
    )
    data = response['data']
    return(data)

def aws_last_mth_bill(start, end, vaultcreds):
    client = boto3.client(
        'ce',
        aws_access_key_id=vaultcreds['access_key'],
        aws_secret_access_key=vaultcreds['secret_key'],
        aws_session_token=vaultcreds['session_token']
    )
    expression = { "Dimensions": { "Key": "RECORD_TYPE", "Values": [ "Usage" ] } }
    try:
        response = client.get_cost_and_usage(
            TimePeriod={
                'Start': start,
                'End': end
            },
            Metrics=[
                'BlendedCost',
            ],
            Granularity='MONTHLY',
            Filter=expression
        )
        amount=response['ResultsByTime'][0]['Total']['BlendedCost']['Amount']
        return(round(Decimal(amount), 2))
    except Exception as e:
        print(e)
        raise e

def send_sns(message, subject, topic, vaultcreds):
    sns_client = boto3.client(
        "sns",
        aws_access_key_id=vaultcreds['access_key'],
        aws_secret_access_key=vaultcreds['secret_key'],
        aws_session_token=vaultcreds['session_token']        
    )
    sns_client.publish(TopicArn=topic, Message=message, Subject=subject)

# Process AWS Bill
aws_creds=get_aws_creds('aws/roles/lambda_role')
aws_bill=aws_last_mth_bill(startdate, enddate, aws_creds)
# Process GCP Bill

# Prepare and send SNS subject and message
subject = 'Last Month Cloud Bills'
message= (
    f"AWS Bill for last month is ${aws_bill}\n"
    + "GCP Bill for last month is $\n"
    + "Azure Bill for last month is $\n"
)
send_sns(message, subject, os.environ["SNS_ARN"], aws_creds)
