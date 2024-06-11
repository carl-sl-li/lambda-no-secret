from datetime import date    
import os
import json
import boto3

print("Loading function")

startdate = '2024-05-01'
enddate = date.today().strftime('%Y-%m')+'-01'

def aws_last_mth_bill(start, end):
    client = boto3.client('ce')
    expression = { "Dimensions": { "Key": "RECORD_TYPE", "Values": [ "Usage" ] } }
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
    return(response)

cost=aws_last_mth_bill(startdate, enddate)
amount=cost['ResultsByTime'][0]['Total']['BlendedCost']['Amount']
amount=float(amount)
print(amount)
print(date.today().strftime('%Y-%m'))
