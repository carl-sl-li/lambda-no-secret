import os
import hvac

vault_client = hvac.Client(url="http://vault.sandpit2.learncmd.com.au:8200")

def get_aws_creds(path):
    vault_client.auth.aws.iam_login(os.environ['AWS_ACCESS_KEY_ID'], os.environ['AWS_SECRET_ACCESS_KEY'], os.environ['AWS_SESSION_TOKEN'])
    response = vault_client.secrets.aws.generate_credentials(
        name=path.split('/')[-1],
        mount_point=path.rsplit('/', 2)[0],
        ttl=900
    )
    data = response['data']
    return(data)

rolepath = 'aws/roles/lambda_role'
print(get_aws_creds(rolepath))

