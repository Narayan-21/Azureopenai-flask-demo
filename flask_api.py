import openai
import PyPDF2
import asyncio
import os
from flask import Flask, jsonify, request
from flask_restful import Api
from utils import MessageBuilder
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (SearchIndex, SearchFieldDataType, SearchField,
                                                   ComplexField, SimpleField, SearchableField,
                                                   CorsOptions)
from azure.search.documents.aio import SearchClient as SearchClient2

app = Flask(__name__)
api = Api(app)

API_KEY = ""

RESOURCE_ENDPOINT = ""

openai.api_type = "azure"

openai.api_key = API_KEY

openai.api_base = RESOURCE_ENDPOINT

openai.api_version = "2023-05-15"

def extract_text_from_pdf(pdf_file):
    text = ""
    pdf_reader = PyPDF2.PdfReader(pdf_file)
    for page in pdf_reader.pages:
        text += page.extract_text()
    return text

@app.route("/home", methods=["POST"])
async def home():
    index_name = request.form.get('index_name')
    search_service_name = request.form.get('search_service_name')
    admin_key = request.form.get('admin_key')
    endpoint = f"https://{search_service_name}.search.windows.net"
    credential = AzureKeyCredential(admin_key)
    client = SearchIndexClient(endpoint=endpoint, credential=credential)
    
    try:
        existing_index = client.get_index(index_name)
    except Exception as e:
            fields = [
                SimpleField(name="id", type=SearchFieldDataType.String, key=True),
                SimpleField(name="title", type=SearchFieldDataType.String, SearchableField=True),
                SimpleField(name="content", type=SearchFieldDataType.String, SearchableField=True),
            ]

            cors_options = CorsOptions(allowed_origins=["*"], max_age_in_seconds=60)
            scoring_profiles = []

            index = SearchIndex(name=index_name, fields=fields, scoring_profiles=scoring_profiles, cors_options=cors_options)
            result = client.create_index(index)
            print(f'Created index - {index_name}')
            #print(result)
    else:
            print(f"The Index {index_name} already exists.")
            
    client2 = SearchClient(endpoint=endpoint, index_name=index_name, credential=credential)
    try:      
        doc_count_initial = client2.get_document_count()
        documents = []
        uploaded_files = request.files.getlist("pdf_files")
        for uploaded_file in uploaded_files:
            file_extension = os.path.splitext(uploaded_file.filename)[1]
            if file_extension.lower() == ".pdf":
                pdf_text = extract_text_from_pdf(uploaded_file)
                document = {
                    "@search.action": "upload",
                    "id": uploaded_file.filename.split('.')[0],
                    "title": os.path.splitext(uploaded_file.filename)[0],
                    "content": pdf_text,
                }
                documents.append(document)
            else:
                return jsonify({"error": "Only PDF files are supported"}), 400
        if documents:
            result = client2.upload_documents(documents)
            print("Documents are being uploaded....")
            #while client2.get_document_count() - doc_count_initial < len(documents):
            #    await asyncio.sleep(1)  # Wait for indexing to complete
            print("Upload of new documents succeeded")
            content=[]
            for i in range(len(documents)):
                res = client2.get_document(key=documents[i]["id"])
                content.append(res)
            system_chat_template = \
"You are an intelligent assistant helping Contoso Inc employees with their healthcare plan questions and employee handbook questions. " + \
"Use 'you' to refer to the individual asking the questions even if they ask with 'I'. " + \
"Answer the following question using only the data provided in the sources below. " + \
"For tabular information return it as an html table. Do not return markdown format. "  + \
"Each source has a name followed by colon and the actual information, always include the source name for each fact you use in the response. " + \
"If you cannot answer using the sources below, say you don't know. Use below example to answer"
            question = """
'What is the deductible for the employee plan for a visit to Overlake in Bellevue?'

Sources:
info1.txt: deductibles depend on whether you are in-network or out-of-network. In-network deductibles are $500 for employee and $1000 for family. Out-of-network deductibles are $1000 for employee and $2000 for family.
info2.pdf: Overlake is in-network for the employee plan.
info3.pdf: Overlake is the name of the area that includes a park and ride near Bellevue.
info4.pdf: In-network institutions include Overlake, Swedish and others in the region
"""
            answer = "In-network deductibles are $500 for employee and $1000 for family [info1.txt] and Overlake is in-network for the employee plan [info2.pdf][info4.pdf]."
            q = request.form.get('question')
            message_builder = MessageBuilder(system_content=system_chat_template, chatgpt_model="gpt-35-turbo")
            #await client2.search(search_text=query)
            user_content = q + "/n" + f"Sources:\n {content}"
            message_builder.append_message('user', user_content)
            message_builder.append_message('assistant', answer)
            message_builder.append_message('user', question)
            messages = message_builder.messages
            #print(messages)
            chat_completion = await openai.ChatCompletion.acreate(
                engine = "dep-1",
                deployment_id = "gpt-35-turbo",
                #engine="gpt-35-turbo",
                messages = messages,
                temperature = 0.3,
                max_tokens = 1024,
                n=1
            )
            return jsonify({"answer":chat_completion.choices[0].message.content}), 200
        else:
            return jsonify({"error": "No valid PDF files were provided"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500