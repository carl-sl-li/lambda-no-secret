import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { join } from "path";
import * as config from 'config';
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as sns from 'aws-cdk-lib/aws-sns';
import { Rule, Schedule } from "aws-cdk-lib/aws-events"
import { LambdaFunction } from "aws-cdk-lib/aws-events-targets";
import { EmailSubscription } from "aws-cdk-lib/aws-sns-subscriptions";

export class LambdaNoSecretStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const configProp: {
      checkBillCron: string;
      emailSubs?: string[],
      gcpBillTableId?: string,
      vaultAWSRole: string,
      vaultGCPRoleSet: string,
      vaultAzureRole: string,
      vaultUrl: string,
    } = config.get('lambdaProps');

    // Create sns topic and add email subscriptions
    const billSnsTopic = new sns.Topic(this, 'billSnsTopic', {
      topicName: 'billSnsTopic',
    });

    if (configProp.emailSubs){
      for (const emailAddress of configProp.emailSubs) {
        billSnsTopic.addSubscription(new EmailSubscription(emailAddress));
      }  
    }

    // Create a lambda role that will authenticate to vault
    const vaultLambdaRole = new iam.Role(this, 'vaultLambdaRole', {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('AWSLambdaExecute')
      ],
      roleName: 'VaultLambdaRole',
    });

    vaultLambdaRole.assumeRolePolicy?.addStatements(new iam.PolicyStatement({
      actions: ['sts:AssumeRole'],
      effect: iam.Effect.ALLOW,
      principals: [new iam.AccountPrincipal(this.account)],
    }));

    // Create a shared lambda layer.
    const sharedLayer = new lambda.LayerVersion(this, 'shared-layer', {
      code: lambda.Code.fromAsset("./python_layers"),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_9],
      layerVersionName: 'shared-layer',
    });

    // Create a lambda function that will be check last month bills.
    const billLambda = new lambda.Function(this, 'billLambda', {
      code: lambda.Code.fromAsset(join(__dirname, "..", "handler")),
      handler: "checklastmonth.lambda_handler",
      runtime: lambda.Runtime.PYTHON_3_9,
      role: vaultLambdaRole,
      environment: {
        SNS_ARN: billSnsTopic.topicArn,
        REGION: this.region,
        GCP_BILL_TABLE: configProp.gcpBillTableId ?? '',
        VAULTAWSPATHS: configProp.vaultAWSRole,
        VAULTGCPPATHS: configProp.vaultGCPRoleSet,
        VAULTAZUREPATHS: configProp.vaultAzureRole,
        VAULTURL: configProp.vaultUrl,
      },
      timeout: cdk.Duration.seconds(30),
      layers: [sharedLayer],
    });

    // Create event rule to trigger the lambda function.
    const billCron = configProp.checkBillCron
    new Rule(this, 'weeklycron', {
      ruleName: 'check-bill-weekly',
      schedule: Schedule.expression(`cron(${billCron})`),
    }).addTarget(new LambdaFunction(billLambda));

    new cdk.CfnOutput(this, 'roleArn',{
      description: 'Role Arn',
      value: vaultLambdaRole.roleArn
    });
  }
}
