from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import base64
import json
import os
import boto3
import hvac
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google.cloud import bigquery

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

def gcp_last_mth_bill(vaultcreds):
    # Set up credentials and build the service
    credentials = service_account.Credentials.from_service_account_info(
        vaultcreds,
        scopes=['https://www.googleapis.com/auth/cloud-platform']
    )

    # Get Project ID
    cloudresourcemanager = build('cloudresourcemanager', 'v1', credentials=credentials)
    project_data = cloudresourcemanager.projects().list().execute()

    # Define your project ID and dataset/table names
    project_id = project_data['projects'][0]['projectId']
    dataset = 'sample_billing'
    table_name = 'sample_table'
    # gcp sample billing data for query
    gcp_sample_table = 'ctg-storage.bigquery_billing_export.gcp_billing_export_v1_01150A_B8F62B_47D999'


    # Initialize the BigQuery client with the credentials
    client = bigquery.Client(credentials=credentials, project=project_id)

    # Calculate the time range for the last month
    end_time = datetime.now(timezone.utc).replace(day=1)
    start_time = (end_time - timedelta(days=1)).replace(day=1)

    # Format the timestamps
    start_time_str = start_time.strftime('%Y-%m-%d')
    end_time_str = end_time.strftime('%Y-%m-%d')

    # Construct the query
    query = f"""
    SELECT
        SUM(cost) AS total_cost,
    FROM
        `{gcp_sample_table}`
    WHERE
    usage_start_time >= TIMESTAMP('{start_time_str}')
    AND usage_start_time < TIMESTAMP('{end_time_str}')
    """

    # Execute the query
    query_job = client.query(query)
    results = query_job.result()

    # Process and display the results
    for row in results:
        amount = row.total_cost
    return(round(Decimal(amount), 2))

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
    gcp_bill=gcp_last_mth_bill(gcp_creds)

    # Prepare and send SNS subject and message
    subject = 'Last Month Cloud Bills'
    message= (
        f"AWS Bill for last month is ${aws_bill}\n"
        + f"GCP Bill for last month is: ${gcp_bill}\n"
        + "Azure Bill for last month is $\n"
    )
    send_sns(message, subject, os.environ["SNS_ARN"], aws_creds)
