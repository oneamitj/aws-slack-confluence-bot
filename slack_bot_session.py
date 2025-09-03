from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import boto3
import logging
import os
import time
import serverless_wsgi

SYSTEM_PROMPT = '''
    You are **RoomyAI**, an internal chatbot for Leapfrog Technology, designed to assist employees by providing accurate and concise answers using company policies, guidelines, and FAQs. All documents are retrieved from Leapfrog Technology’s **Confluence space**, which includes up-to-date information on company procedures, HR policies, company guidelines, general company information, and more.
    **Your Task**:
    - Utilize the retrieved Confluence documents as the **primary source of truth**. Always base your answers on the information from these documents, prioritizing accuracy and relevance.
    - Maintain a **professional, respectful, and friendly tone**. Aim to provide concise responses but include enough context to be helpful.
    - Uphold **data privacy and confidentiality**. Do not disclose sensitive information unless it is explicitly available in the retrieved content. If the user asks for information that might be sensitive or not available in the knowledge base, advise them to contact the appropriate department (e.g., HR, IT).
    - Clarify when needed and guide the user to additional resources or contacts if the query cannot be answered directly from the knowledge base.
    - Be proactive in identifying when a policy or guideline may need further clarification based on your internal documents and suggest the relevant document or section for the user to refer to.
    **Key Instructions**:
    1. **Leverage Document Context**: If the answer requires specific details from a policy or document, reference that information clearly. For example, "According to the Confluence HR policy document on leave entitlements...".
    2. **Handle Ambiguity Gracefully**: If the query is unclear or the retrieved information is insufficient, ask the user for more details or suggest a relevant Confluence page for further reading.
    3. **Guide for Escalations**: For queries involving sensitive or unresolved issues (e.g., legal, complaints, personal grievances), advise the user to consult HR or the relevant department directly.
    **Example Responses**:
    1. **Policy Inquiry**:
       - User: "What is the current leave policy?"
       - Response: "According to the HR Leave Policy document on Confluence, employees are entitled to 20 days of paid leave per year. For more details, please refer to the HR Policies page or contact HR for specific cases."
    2. **Technical Issue**:
       - User: "I need access to the new software tool."
       - Response: "Access to new software tools is managed by the IT department. Please refer to the IT Access Request Guide on Confluence or submit a request via the internal portal."
    3. **Ambiguous Query**:
       - User: "What are the office timings?"
       - Response: "Office timings may vary based on the department. Please refer to the 'Work Hours and Flexibility' section on the Confluence Employee Handbook for specific guidelines."
    
    The retrieved documents for the user query are: $search_results$
    The response generation format: $output_format_instructions$
    '''

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
app = Flask(__name__)
slack_token = os.getenv('SLACK_BOT_TOKEN', "xoxb-***")
client = WebClient(token=slack_token)
processed_events = set()
bot_user_id = client.auth_test()["user_id"]

session = boto3.Session()
aws_region = session.region_name

bedrock_agent_runtime = session.client('bedrock-agent-runtime')
kb_id = os.getenv('KB_ID', "ZY***")
bedrock_model_id = os.getenv("MODEL_ID", "us.amazon.nova-pro-v1:0")

dynamodb = boto3.resource('dynamodb', region_name=aws_region)
dynamodb_table_name = os.getenv('DYNAMODB_TABLE_NAME', "SlackBotSessionTable")
table = dynamodb.Table(dynamodb_table_name)

@app.route("/", methods=["GET"])
def init():
    logger.debug({"status": "ok"})
    return jsonify({"status": "ok"})

@app.route("/slack/events", methods=["POST"])
def slack_events():
    data = request.json
    event_id = data.get("event_id")
    logger.debug(f"Received data: {data}")

    # Handle Slack URL verification challenge
    if "type" in data and data["type"] == "url_verification":
        return jsonify({"challenge": data["challenge"]})

    if event_id in processed_events:
        logger.debug(f"Duplicate event detected: {event_id}")
        return jsonify({"status": "duplicate"})

    # Mark event as processed
    processed_events.add(event_id)

    # Process events
    if "event" in data:
        event = data["event"]
        event_type = event.get("type")

        # Only respond to direct messages (DMs)
        if event_type == "message" and "subtype" not in event:
            user_id = event.get("user")
            channel_type = event.get("channel_type")
            user_message = event.get("text")
            channel_id = event.get("channel")
            logger.debug(f"Received message: {user_message}")

            # Respond if the message is in a direct message (IM)
            if user_id != bot_user_id and channel_type == "im":
                try:
                    # Check if the user has a session ID
                    session_id = get_session_id(user_id)

                    # Request with session ID
                    response, new_session_id = query_knowledgebase(user_message, session_id)

                    # Update session ID if it has changed
                    if new_session_id != session_id:
                        set_session_id(user_id, new_session_id)

                    client.chat_postMessage(channel=channel_id, text=response)
                except SlackApiError as e:
                    logger.error(f"Error posting message: {e.response['error']}")

    return jsonify({"status": "ok", "page": "events"})


def query_knowledgebase(message, session_id=None):
    if session_id is None:
        response = bedrock_agent_runtime.retrieve_and_generate(
            input={
                'text': message
            },
            retrieveAndGenerateConfiguration={
                'type': 'KNOWLEDGE_BASE',
                'knowledgeBaseConfiguration': {
                    'generationConfiguration': {
                        'promptTemplate': {
                            'textPromptTemplate': system_prompt
                        }
                    },
                    'knowledgeBaseId': kb_id,
                    'modelArn': 'anthropic.claude-3-sonnet-20240229-v1:0',
                }
            }
        )
    else:
        response = bedrock_agent_runtime.retrieve_and_generate(
            input={
                'text': message
            },
            sessionId=session_id,
            retrieveAndGenerateConfiguration={
                'type': 'KNOWLEDGE_BASE',
                'knowledgeBaseConfiguration': {
                    'generationConfiguration': {
                        'promptTemplate': {
                            'textPromptTemplate': system_prompt
                        }
                    },
                    'knowledgeBaseId': kb_id,
                    'modelArn': 'anthropic.claude-3-sonnet-20240229-v1:0',
                }
            }
        )

    # Extract main text and initialize output with it
    output_text = response["output"]["text"]

    # Prepare a list for markdown citation references
    references = []
    citation_distance = 0

    # Loop through citations to append in-text citation markers and markdown references
    for index, citation in enumerate(response["citations"], start=1):
        if len(citation["retrievedReferences"]) == 0:
            continue
        span = citation["generatedResponsePart"]["textResponsePart"]["span"]

        # Prepare in-text citation marker
        citation_marker = f"[{index}]"

        # Extract title and URL for markdown reference list
        metadata = citation["retrievedReferences"][0]["metadata"]
        title = metadata["x-amz-bedrock-kb-title"]
        url = metadata["x-amz-bedrock-kb-source-uri"]
        citation_marker = f" <{url}|{citation_marker}>"
        end = span["end"] + citation_distance
        output_text = output_text[:end] + citation_marker + output_text[end:]
        citation_distance += len(citation_marker)

        # Append to references list in markdown format
        references.append(f"[{index}] <{url}|{title}>")

    # Append references to the end of the output text
    output_text += "\n\n" + "\n".join(references)
    return output_text, response["sessionId"]

def set_session_id(userId, session_id):
    timestamp = int(time.time())

    try:
        # Store sessionId and timestamp in DynamoDB
        table.put_item(
            Item={
                'userId': userId,
                'sessionId': session_id,
                'timestamp': timestamp
            }
        )
    except Exception as e:
        logger.error(f"Error storing sessionId: {e}")
        return None
    return session_id

def get_session_id(userId):
    try:
        response = table.get_item(Key={'userId': userId})

        # Check if the session exists
        if 'Item' not in response:
            return None

        item = response['Item']
        session_id = item['sessionId']
        timestamp = item['timestamp']
        current_time = int(time.time())

        # Check if the session has expired
        if current_time - timestamp > 86400:
            # Session is expired, clear it
            # clear_session_id(userId)
            return None

        logger.info(f"Retrieved sessionId: {session_id}")
        return session_id
    except Exception as e:
        logger.error(f"Error retrieving sessionId: {e}")
        return None

# def clear_session_id(userId):
#     """
#     Clears the sessionId for the user from DynamoDB.
#     """
#     table.delete_item(Key={'userId': userId})

@app.route("/slack/interact", methods=["POST"])
def slack_interact():
    data = request.json
    logger.debug(f"Received data: {data}")
    return jsonify({"status": "ok", "page": "interact"})


# Remove the __main__ block and add the lambda handler
def lambda_handler(event, context):
    """
    AWS Lambda handler for Flask app via Function URL.
    """
    return serverless_wsgi.handle_request(app, event, context)
