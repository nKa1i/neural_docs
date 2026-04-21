import os

base_dir = r"c:\Users\Roza\Downloads\digital_farabi_TO\digital_farabi\company_projects"

# Project 1: 10 documents
p1_dir = os.path.join(base_dir, "Project_Alpha_10Docs")
os.makedirs(p1_dir, exist_ok=True)

# Generate 10 large files
for i in range(1, 11):
    file_path = os.path.join(p1_dir, f"doc_{i}.txt")
    if i == 1:
        content = "Project Alpha Goals.\n" * 50 + "\nWe need to build a distributed cache system.\nThe budget is $1,000,000.\nThe timeline is 12 months."
    elif i == 2:
        content = "Technical Requirements:\n" * 50 + "\nMust use Redis and Golang.\nBudget is actually $1,200,000."
    elif i == 3:
        content = "Team composition:\n" * 50 + "\nWe need 5 Senior Golang developers.\nTimeline is 14 months due to hiring delays."
    elif i == 4:
        content = "Architecture:\n" * 50 + "\nMicroservices architecture.\nEvent-driven with Kafka."
    elif i == 5:
        content = "Risks:\n" * 50 + "\nData loss risk is high.\nMitigation: multi-region replication."
    elif i == 6: # large code file
        content = "def calculate_hash(data):\n" + "    # This is a dummy function\n" * 100 + "    return hash(data)"
    elif i == 7:
        content = "API Specification:\n" + "GET /cache/{key}\n" * 100
    elif i == 8:
        content = "Deployment:\n" + "Kubernetes deployment required.\n" * 50 + "Timeline: Deploy in 10 months."
    elif i == 9:
        content = "Testing Strategy:\n" + "Unit tests must cover 90%.\n" * 50
    elif i == 10:
        content = "Security Policies:\n" + "All data at rest must be encrypted.\n" * 50

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

# Project 2: 5 documents
p2_dir = os.path.join(base_dir, "Project_Beta_5Docs")
os.makedirs(p2_dir, exist_ok=True)

for i in range(1, 6):
    file_path = os.path.join(p2_dir, f"doc_{i}.txt")
    if i == 1:
        content = "Project Beta Overview.\n" * 100 + "\nGoal: Build an AI-powered CRM.\nBudget: $500,000.\nTimeline: 6 months."
    elif i == 2:
        content = "Frontend Details:\n" * 100 + "\nUse React and TypeScript.\nWait, new budget estimation is $600,000."
    elif i == 3:
        content = "Backend Details:\n" * 100 + "\nUse Node.js and PostgreSQL.\nTimeline extended to 8 months."
    elif i == 4:
        content = "Security Requirements:\n" * 100 + "\nOAuth2 implementation required."
    elif i == 5: # Large code file
        content = "class CRM:\n" + "    def __init__(self):\n        pass\n" * 100

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

print("Test projects generated successfully.")
