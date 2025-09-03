# AWS Slack Confluence Bot

This repository contains a Slack bot that integrates with AWS Bedrock and a Confluence knowledge base to answer questions. The bot can be deployed as an AWS Lambda function.

## Features

- **Slack Integration**: The bot listens to events from Slack and responds to direct messages.
- **AWS Bedrock Integration**: It uses AWS Bedrock's `retrieve_and_generate` functionality to query a knowledge base.
- **Confluence Knowledge Base**: The bot is designed to work with a knowledge base created from a Confluence space.
- **Two Versions**:
    - `slack_bot_simple.py`: A simple version of the bot.
    - `slack_bot_session.py`: A version that maintains conversation sessions using DynamoDB.
- **Infrastructure as Code**:
    - AWS CDK script (`cdk_iac/deploy.py`) for deploying the necessary infrastructure.
    - AWS CloudFormation template (`cloudformation/stack-for-lambda.yaml`) for deploying the Lambda function and related resources.

## Architecture

The bot is a Flask application that is deployed as an AWS Lambda function. It uses the `serverless-wsgi` library to handle the Lambda proxy integration with the Flask app.

1.  A user sends a direct message to the bot in Slack.
2.  Slack sends an event to the Lambda function's URL.
3.  The Flask application receives the event and verifies it.
4.  The bot calls the AWS Bedrock `retrieve_and_generate` API with the user's message.
5.  Bedrock queries the Confluence knowledge base and generates a response.
6.  The bot formats the response, including citations from the Confluence documents.
7.  The bot posts the response back to the user in Slack.

The `slack_bot_session.py` version also uses a DynamoDB table to store session information for each user, allowing for conversational context.

## Prerequisites

- Python 3.x
- An AWS account with credentials configured.
- A Slack workspace with a bot token.
- An AWS Bedrock knowledge base configured with your Confluence space.

## Installation

1.  Clone the repository:
    ```bash
    git clone https://github.com/oneamitj/aws-slack-confluence-bot.git
    cd aws-slack-confluence-bot
    ```

2.  Install the required Python packages:
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

The application requires the following environment variables to be set:

- `SLACK_BOT_TOKEN`: Your Slack bot token.
- `KB_ID`: The ID of your AWS Bedrock knowledge base.
- `MODEL_ID`: The ID of the Bedrock model to use (e.g., `anthropic.claude-3-sonnet-20240229-v1:0`).
- `DYNAMODB_TABLE_NAME` (for `slack_bot_session.py`): The name of the DynamoDB table for storing sessions.

## Deployment

You can deploy the application using either AWS CDK or AWS CloudFormation.

### AWS CDK

The `cdk_iac/deploy.py` script can be used to deploy the infrastructure. You will need to have the AWS CDK installed and configured.

```bash
# You might need to adapt the cdk script to your needs
cd cdk_iac
# cdk deploy
```

### AWS CloudFormation

The `cloudformation/stack-for-lambda.yaml` template can be used to deploy the Lambda function and an API Gateway.

1.  Package the Lambda function:
    ```bash
    zip slack-bot-lambda.zip slack_bot_simple.py
    # or
    zip slack-bot-lambda.zip slack_bot_session.py
    ```
    You will also need to include the installed packages in the zip file.

2.  Upload the `slack-bot-lambda.zip` file to an S3 bucket.

3.  Deploy the CloudFormation stack using the AWS Management Console or the AWS CLI, providing the S3 bucket and key for the zip file, and the required environment variables as parameters.

## Usage

Once deployed, you will get a URL for your Lambda function. You need to configure this URL in your Slack app's "Event Subscriptions" settings.

The bot will then respond to direct messages sent to it in Slack.

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.
