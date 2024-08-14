from datetime import datetime, timedelta, timezone
from decimal import Decimal
import base64
import json
import os
import boto3
import hvac
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google.cloud import bigquery
from azure.identity import ClientSecretCredential
from azure.mgmt.costmanagement import CostManagementClient

print("Loading function")

# Define Vault python client
vault_client = hvac.Client(url=os.environ['VAULTURL'])

end_time = datetime.now(timezone.utc).replace(day=1)
start_time = (end_time - timedelta(days=1)).replace(day=1)
startdate = start_time.strftime('%Y-%m')+'-01'
enddate = end_time.strftime('%Y-%m')+'-01'

def auth_to_vault():
    vault_client.auth.aws.iam_login(os.environ['AWS_ACCESS_KEY_ID'], os.environ['AWS_SECRET_ACCESS_KEY'], os.environ['AWS_SESSION_TOKEN'])

# AWS Functions
def get_aws_creds(path:str):
    response = vault_client.secrets.aws.generate_credentials(
        name=path.split('/')[-1],
        mount_point=path.rsplit('/', 2)[0],
        ttl=900
    )
    data = response['data']
    return(data)

def aws_last_mth_bill(start:str, end:str, vaultcreds:str):
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
def get_gcp_creds(path:str):
    response = vault_client.secrets.gcp.generate_service_account_key(
        roleset=path.split('/')[-1],
        mount_point=path.rsplit('/', 2)[0]
    )
    data = response['data']['private_key_data']
    credfile = json.loads(base64.b64decode(data))
    return(credfile)

def gcp_last_mth_bill(start:str, end:str, vaultcreds:str):
    # Set up credentials and build the service
    credentials = service_account.Credentials.from_service_account_info(
        vaultcreds,
        scopes=['https://www.googleapis.com/auth/cloud-platform']
    )

    # Get Project ID
    cloudresourcemanager = build('cloudresourcemanager', 'v1', credentials=credentials)
    project_data = cloudresourcemanager.projects().list().execute()
    project_id = project_data['projects'][0]['projectId']

    gcp_table = os.environ['GCP_BILL_TABLE']

    # Initialize the BigQuery client with the credentials
    client = bigquery.Client(credentials=credentials, project=project_id)

    # Construct the query
    query = f"""
    SELECT
        SUM(cost) AS total_cost,
    FROM
        `{gcp_table}`
    WHERE
    usage_start_time >= TIMESTAMP('{start}')
    AND usage_start_time < TIMESTAMP('{end}')
    """

    # Execute the query
    query_job = client.query(query)
    results = query_job.result()

    # Process and display the results
    for row in results:
        amount = row.total_cost
    return(round(Decimal(amount), 2))

# Azure Functions
def read_azure_config(path):
    response = vault_client.secrets.azure.read_config(
        mount_point=path.rsplit('/', 2)[0]
    )
    data = response
    return(data)

def get_azure_creds(path):
    response = vault_client.secrets.azure.generate_credentials(
        name=path.split('/')[-1],
        mount_point=path.rsplit('/', 2)[0]
    )
    data = response
    return(data)

def azure_last_mth_bill(start:datetime, end:datetime, vaultcreds, config):

    subscription_id = config['subscription_id']
    # Authenticate using ClientSecretCredential
    credential = ClientSecretCredential(
        client_id=vaultcreds['client_id'],
        client_secret=vaultcreds['client_secret'],
        tenant_id=config['tenant_id']
    )
    
    # Create a CostManagementClient
    client = CostManagementClient(credential)  

    # Create the query
    query = {
        "type": "Usage",
        "timeframe": "Custom",
        "timePeriod": {
            "from": start.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "to": end.strftime('%Y-%m-%dT%H:%M:%SZ')
        },
        "dataset": {
            "granularity": "None",
            "aggregation": {
                "totalCost": {
                    "name": "Cost",
                    "function": "Sum"
                }
            }
        }
    }

    # Execute the query
    result = client.query.usage(
        scope=f"/subscriptions/{subscription_id}",
        parameters=query
    )

    # Print the total cost
    if result and result.rows:
        total_cost = result.rows[0][0]
        return(round(Decimal(total_cost), 2))
    else:
        return(round(Decimal(0), 2))

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
    gcp_bill=gcp_last_mth_bill(startdate, enddate, gcp_creds)
    # Process Azure Bill
    azure_config = read_azure_config(os.environ['VAULTAZUREPATHS'])
    azure_cred = get_azure_creds(os.environ['VAULTAZUREPATHS'])
    azure_bill = azure_last_mth_bill(start_time, end_time, azure_cred, azure_config)

    # Prepare and send SNS subject and message
    subject = 'Last Month Cloud Bills'
    message= (
        f"AWS Bill for last month is ${aws_bill}\n"
        + f"GCP Bill for last month is: ${gcp_bill}\n"
        + f"Azure Bill for last month is ${azure_bill}\n"
    )
    send_sns(message, subject, os.environ["SNS_ARN"], aws_creds)
