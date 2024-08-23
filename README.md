# Welcome to your CDK TypeScript project

This is a blank project for CDK development with TypeScript.

The `cdk.json` file tells the CDK Toolkit how to execute your app.

## Useful commands

* `npm run build`   compile typescript to js
* `npm run watch`   watch for changes and compile
* `npm run test`    perform the jest unit tests
* `npx cdk deploy`  deploy this stack to your default AWS account/region
* `npx cdk diff`    compare deployed stack with current state
* `npx cdk synth`   emits the synthesized CloudFormation template

## Setup Python Layers

Requirements: Docker – needs to be installed on your local machine

cryptography library contains native code and that code is compiled for the architecture of the current machine. AWS Lambda needs Layers compiled as Linux ELF shared objects, hence using a python:3.9 docker image to build python layers.
```
$ cd python_layers
$ docker run -it --mount type=bind,src=$(pwd),dst=$(pwd)/ python:3.9 pip install -r $(pwd)/requirements.txt --target $(pwd)/python --platform manylinux2014_x86_64 --only-binary=:all:
```

## CDK Parameters

config/development.yaml

`checkBillCron` - How often to run the Lambda function (e.g. 0 22 ? * SUN *)

`gcpBillTableId` - GCP BigQuery Bill Data Table ID (e.g ctg-storage.bigquery_billing_export.gcp_billing_export_v1_01150A_B8F62B_47D999)
  
`vaultUrl` - URL of hashcorp vault (e.g. http://example.com.au:8200)

`vaultAWSRole` - Hashicop Vault Path to the AWS Secrets (e.g. aws/sandpit1/roles/lambda_role)

`vaultGCPRoleSet` - Hashicop Vault Path to the GCP Secrets (e.g. gcp/sandpit1/roleset/lambda_role)

`vaultAzureRole` - Hashicop Vault Path to the Azure Secrets (e.g. azure/sandpit1/roles/lambda_role)
  
`emailSubs` - list of email(s) to recieve SNS email notification (e.g. [ john@example.com ])
