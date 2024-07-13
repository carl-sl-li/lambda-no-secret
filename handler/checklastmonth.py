from datetime import date, timedelta
from decimal import Decimal
import base64
import json
import os
import boto3
import hvac
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import timedelta

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

# AWS Functions
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

# GCP Functions
def get_gcp_creds(path):
    response = vault_client.secrets.gcp.generate_service_account_key(
        roleset=path.split('/')[-1],
        mount_point=path.rsplit('/', 2)[0]
    )
    data = response['data']['private_key_data']
    credfile = json.loads(base64.b64decode(data))
    return(credfile)

def get_gcp_billing_info(vaultcreds):
    # Set up credentials and build the service
    credentials = service_account.Credentials.from_service_account_info(
        vaultcreds,
        scopes=['https://www.googleapis.com/auth/cloud-platform']
    )

    cloudresourcemanager = build('cloudresourcemanager', 'v1', credentials=credentials)
    cloudbilling = build('cloudbilling', 'v1', credentials=credentials)

    # Get Project ID
    project_data = cloudresourcemanager.projects().list().execute()
    project_id = 'projects/' + project_data['projects'][0]['projectId']

    # Get Billing Info
    request = cloudbilling.projects().getBillingInfo(
        name=project_id,
    )

    response = request.execute()
    return(response)

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
    # Get GCP Billing Info
    gcp_creds=get_gcp_creds(os.environ['VAULTGCPPATHS'])
    gcp_bill_info=get_gcp_billing_info(gcp_creds)
    gcp_project_id=gcp_bill_info['projectId']
    gcp_billing_acc=gcp_bill_info['billingAccountName']

    # Prepare and send SNS subject and message
    subject = 'Last Month Cloud Bills'
    message= (
        f"AWS Bill for last month is ${aws_bill}\n"
        + f"GCP Project Id: {gcp_project_id}, Billing Account: {gcp_billing_acc}.\n"
        + "Azure Bill for last month is $\n"
    )
    send_sns(message, subject, os.environ["SNS_ARN"], aws_creds)
