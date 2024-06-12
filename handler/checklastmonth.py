from datetime import date, timedelta
from decimal import Decimal
import os
import json
import boto3

print("Loading function")

today = date.today()
firstofmonth = today.replace(day=1)
lastmonth = firstofmonth - timedelta(days=1)
startdate = lastmonth.strftime('%Y-%m')+'-01'
enddate = today.strftime('%Y-%m')+'-01'

def aws_last_mth_bill(start, end):
    client = boto3.client('ce')
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

def send_sns(message, subject, topic):
    client = boto3.client("sns")
    client.publish(TopicArn=topic, Message=message, Subject=subject)

def lambda_handler(event, context):
    print("Received event: " + json.dumps(event, indent=2))
    aws_bill=aws_last_mth_bill(startdate, enddate)
    subject = 'Last Month Cloud Bills'
    message= (
        f"AWS Bill for last month is ${aws_bill}\n"
        + "GCP Bill for last month is $\n"
        + "Azure Bill for last month is $\n"
    )
    send_sns(message, subject, os.environ["SNS_ARN"])
