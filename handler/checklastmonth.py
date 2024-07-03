from datetime import date, timedelta
from decimal import Decimal
import base64
import json
import os
import boto3
import hvac

print("Loading function")

# Define Vault python client
vault_client = hvac.Client(url=os.environ['VAULTURL'])

today = date.today()
firstofmonth = today.replace(day=1)
lastmonth = firstofmonth - timedelta(days=1)
startdate = lastmonth.strftime('%Y-%m')+'-01'
enddate = today.strftime('%Y-%m')+'-01'

def auth_to_vault():
    vault_client.auth.aws.iam_login(os.environ['AWS_ACCESS_KEY_ID'], os.environ['AWS_SECRET_ACCESS_KEY'], os.environ['AWS_SESSION_TOKEN'])

# AWS Get Usage Functions
def get_aws_creds(path):
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

# GCP Get Usage Functions
def get_gcp_creds(path):
    response = vault_client.secrets.gcp.generate_service_account_key(
        roleset=path.split('/')[-1],
        mount_point=path.rsplit('/', 2)[0]
    )
    data = response['data']['private_key_data']
    credfile = json.loads(base64.b64decode(data))
    return(credfile)

def send_sns(message, subject, topic, vaultcreds):
    client = boto3.client(
        "sns",
        aws_access_key_id=vaultcreds['access_key'],
        aws_secret_access_key=vaultcreds['secret_key'],
        aws_session_token=vaultcreds['session_token']        
    )
    client.publish(TopicArn=topic, Message=message, Subject=subject)

def lambda_handler(event, context):
    print("Received event: " + json.dumps(event, indent=2))
    # Athenticate to Vault
    auth_to_vault()
    # Process AWS Bill
    aws_creds=get_aws_creds(os.environ['VAULTAWSPATHS'])
    aws_bill=aws_last_mth_bill(startdate, enddate, aws_creds)
    # Process GCP Bill
    gcp_creds=get_gcp_creds(os.environ['VAULTGCPPATHS'])
    print(gcp_creds)

    # Prepare and send SNS subject and message
    subject = 'Last Month Cloud Bills'
    message= (
        f"AWS Bill for last month is ${aws_bill}\n"
        + "GCP Bill for last month is $\n"
        + "Azure Bill for last month is $\n"
    )
    send_sns(message, subject, os.environ["SNS_ARN"], aws_creds)
