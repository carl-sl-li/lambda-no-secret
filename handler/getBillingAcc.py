from datetime import date, datetime, timedelta, timezone
import base64
import os
import json
import boto3
import hvac
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google.cloud import bigquery
from azure.identity import ClientSecretCredential
from azure.mgmt.consumption import ConsumptionManagementClient
from azure.mgmt.costmanagement import CostManagementClient

print("Loading function")

today = date.today()
firstofmonth = today.replace(day=1)
lastmonth = firstofmonth - timedelta(days=1)
startdate = lastmonth.strftime('%Y-%m')+'-01'
enddate = today.strftime('%Y-%m')+'-01'
vault_client = hvac.Client(url=os.environ['VAULT_ADDR'])

def auth_to_vault():
    vault_client.auth.aws.iam_login(os.environ['AWS_ACCESS_KEY_ID'], os.environ['AWS_SECRET_ACCESS_KEY'], os.environ['AWS_SESSION_TOKEN'])

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

def get_gcp_creds(path):
    response = vault_client.secrets.gcp.generate_service_account_key(
        roleset=path.split('/')[-1],
        mount_point=path.rsplit('/', 2)[0]
    )
    data = response['data']['private_key_data']
    credfile = json.loads(base64.b64decode(data))
    return(credfile)

def send_sns(message, subject, topic, vaultcreds):
    sns_client = boto3.client(
        "sns",
        aws_access_key_id=vaultcreds['access_key'],
        aws_secret_access_key=vaultcreds['secret_key'],
        aws_session_token=vaultcreds['session_token']        
    )
    sns_client.publish(TopicArn=topic, Message=message, Subject=subject)

# Process AWS Bill
# aws_creds=get_aws_creds('aws/roles/lambda_role')
# aws_bill=aws_last_mth_bill(startdate, enddate, aws_creds)
# Process GCP Bill
auth_to_vault()
# gcp_creds=get_gcp_creds('gcp/carlli/roleset/lambda_role')
# print(gcp_creds)

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
    return(response['projectId'], response['billingAccountName'])

def gcp_last_mth_bill(start:str, end:str, vaultcreds:str, sample:bool):
    # Set up credentials and build the service
    credentials = service_account.Credentials.from_service_account_info(
        vaultcreds,
        scopes=['https://www.googleapis.com/auth/cloud-platform']
    )

    # Get Project ID
    cloudresourcemanager = build('cloudresourcemanager', 'v1', credentials=credentials)
    project_data = cloudresourcemanager.projects().list().execute()
    project_id = project_data['projects'][0]['projectId']

    # Define your project ID and dataset/table names
    table_id = 'weighty-works-430022-u8.sample_billing.gcp_billing_export_v1_01CB25_64E872_28B129'
    # gcp sample billing data for query
    gcp_sample_table = 'ctg-storage.bigquery_billing_export.gcp_billing_export_v1_01150A_B8F62B_47D999'

    if sample:
        query_table = gcp_sample_table
    else:
        query_table = table_id
    # Initialize the BigQuery client with the credentials
    client = bigquery.Client(credentials=credentials, project=project_id)

    # Construct the query
    query = f"""
    SELECT
        SUM(cost) AS total_cost,
    FROM
        `{query_table}`
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

def azure_last_mth_bill(vaultcreds, config):

    subscription_id = config['subscription_id']
    # Authenticate using ClientSecretCredential
    credential = ClientSecretCredential(
        client_id=vaultcreds['client_id'],
        client_secret=vaultcreds['client_secret'],
        tenant_id=config['tenant_id']
    )
    
    # Create a CostManagementClient
    client = CostManagementClient(credential)  

    # Define the time period for the query (last month)
    end_date = datetime.now(timezone.utc)
    start_date = end_date.replace(day=1) - timedelta(days=1)
    start_date = start_date.replace(day=1)

    # Create the query
    query = {
        "type": "Usage",
        "timeframe": "Custom",
        "timePeriod": {
            "from": start_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "to": end_date.strftime('%Y-%m-%dT%H:%M:%SZ')
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
        print(f"Total cost for the last month: ${total_cost}")
    else:
        print("No cost data available for the specified period.")

azure_config = read_azure_config('azure/carlli/roles/lambda_role')
azure_cred = get_azure_creds('azure/carlli/roles/lambda_role')
azure_last_mth_bill(azure_cred, azure_config)
