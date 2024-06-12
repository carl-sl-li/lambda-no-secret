import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { join } from "path";
import * as config from 'config';
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as sns from 'aws-cdk-lib/aws-sns';
import { EmailSubscription } from "aws-cdk-lib/aws-sns-subscriptions";

export class LambdaNoSecretStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const configProp: {
      vaultPaths: string[],
      emailSubs?: string[],
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

    // Create sns policy needed for the lambda functions.
    const snsPolicy = new iam.PolicyStatement({
      actions: ["sns:publish"],
      effect: iam.Effect.ALLOW,
      resources: [billSnsTopic.topicArn],
      sid: "AllowSnsAccess",
    });

    const cePolicy = new iam.PolicyStatement({
      actions: ["ce:Get*"],
      effect: iam.Effect.ALLOW,
      resources: ['*'],
      sid: "CostExplorerReadOnlyAccess",
    });

    // Create a lambda function that will be check last month bills.
    const billLambda = new lambda.Function(this, 'billLambda', {
      code: lambda.Code.fromAsset(join(__dirname, "..", "handler")),
      handler: "checklastmonth.lambda_handler",
      runtime: lambda.Runtime.PYTHON_3_9,
      environment: {
        SNS_ARN: billSnsTopic.topicArn,
        REGION: this.region,
        VAULTPATHS: configProp.vaultPaths.join(),
      },
      timeout: cdk.Duration.seconds(30),
    });
    billLambda.addToRolePolicy(snsPolicy);
    billLambda.addToRolePolicy(cePolicy);
  }
}
