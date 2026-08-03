"""Curated skill/keyword vocabulary for offline (no-LLM) resume parsing.

Each canonical skill maps to a list of surface forms (English + Hebrew) to match
in resume and job text. Kept intentionally broad for tech + adjacent roles.
"""
from __future__ import annotations

# canonical -> aliases (lowercased matching is applied at runtime)
SKILLS: dict[str, list[str]] = {
    # languages
    "Python": ["python", "פייתון"],
    "JavaScript": ["javascript", "ג'אווהסקריפט"],
    "TypeScript": ["typescript"],
    "Java": ["java", "ג'אווה"],
    "C#": ["c#", "csharp", ".net", "dotnet"],
    "C++": ["c++", "cpp"],
    "C": ["\bc\b"],
    "Go": ["golang", "go lang"],
    "Rust": ["rust"],
    "Ruby": ["ruby", "rails", "ruby on rails"],
    "PHP": ["php", "laravel"],
    "Kotlin": ["kotlin"],
    "Swift": ["swift"],
    "Scala": ["scala"],
    "R": ["\br language\b"],
    "SQL": ["sql", "מסדי נתונים"],
    # frontend
    "React": ["react", "reactjs", "react.js", "ריאקט"],
    "Angular": ["angular", "angularjs"],
    "Vue": ["vue", "vuejs", "vue.js"],
    "Next.js": ["next.js", "nextjs"],
    "HTML/CSS": ["html", "css", "scss", "sass", "tailwind"],
    "Redux": ["redux"],
    # backend / frameworks
    "Node.js": ["node", "nodejs", "node.js"],
    "FastAPI": ["fastapi"],
    "Django": ["django"],
    "Flask": ["flask"],
    "Spring": ["spring", "spring boot"],
    "Express": ["express", "expressjs"],
    "NestJS": ["nestjs", "nest.js"],
    "GraphQL": ["graphql"],
    "REST": ["rest", "restful", "rest api"],
    "gRPC": ["grpc"],
    "Microservices": ["microservice", "microservices", "מיקרו-שירותים"],
    "Event-Driven": ["event-driven", "event driven", "message queue"],
    "RabbitMQ": ["rabbitmq"],
    "Camunda": ["camunda", "zeebe"],
    # data / ML
    "AI": ["ai", "artificial intelligence", "gen ai", "generative ai", "genai",
           "בינה מלאכותית"],
    "Machine Learning": ["machine learning", "ml", "למידת מכונה", "לימוד מכונה"],
    "Deep Learning": ["deep learning", "dl", "למידה עמוקה"],
    "NLP": ["nlp", "natural language", "עיבוד שפה טבעית"],
    "Computer Vision": ["computer vision", "opencv", "ראייה ממוחשבת", "ראיה ממוחשבת"],
    "LLM": ["llm", "large language model", "gpt", "prompt engineering", "rag", "מודל שפה"],
    "Algorithms": ["algorithms", "algorithm engineer", "אלגוריתמים", "אלגוריתמיקה"],
    "PyTorch": ["pytorch", "torch"],
    "TensorFlow": ["tensorflow", "keras"],
    "scikit-learn": ["scikit", "sklearn", "scikit-learn"],
    "Pandas": ["pandas", "numpy"],
    "Spark": ["spark", "pyspark"],
    "Airflow": ["airflow"],
    "Kafka": ["kafka"],
    "Data Engineering": ["data engineering", "etl", "data pipeline", "הנדסת נתונים"],
    "Data Science": ["data science", "data scientist", "מדעני נתונים", "מדע הנתונים"],
    # databases
    "PostgreSQL": ["postgres", "postgresql"],
    "MySQL": ["mysql", "mariadb"],
    "MongoDB": ["mongo", "mongodb"],
    "Redis": ["redis"],
    "Elasticsearch": ["elasticsearch", "elastic", "opensearch"],
    "Snowflake": ["snowflake"],
    "BigQuery": ["bigquery"],
    "DynamoDB": ["dynamodb"],
    # cloud / infra / devops
    "AWS": ["aws", "amazon web services", "ec2", "s3", "lambda"],
    "GCP": ["gcp", "google cloud"],
    "Azure": ["azure"],
    "Kubernetes": ["kubernetes", "k8s"],
    "OpenShift": ["openshift"],
    "Helm": ["helm"],
    "Docker": ["docker", "containers"],
    "Terraform": ["terraform"],
    "CI/CD": ["ci/cd", "cicd", "jenkins", "github actions", "gitlab ci", "circleci"],
    "GitLab": ["gitlab"],
    "Git": ["\\bgit\\b", "github", "bitbucket", "version control"],
    "Linux": ["linux", "unix", "bash"],
    "DevOps": ["devops", "sre", "site reliability"],
    "Ansible": ["ansible"],
    "VMware": ["vmware", "virtualization", "virtualized"],
    "Prometheus": ["prometheus", "grafana"],
    # mobile
    "iOS": ["ios", "swiftui", "objective-c"],
    "Android": ["android"],
    "React Native": ["react native"],
    "Flutter": ["flutter", "dart"],
    # security
    "Cybersecurity": ["cybersecurity", "cyber security", "infosec", "סייבר", "אבטחת מידע"],
    "Penetration Testing": ["penetration testing", "pentest", "red team"],
    "SIEM": ["siem", "soc analyst"],
    # QA
    "QA/Automation": ["qa", "quality assurance", "test automation", "selenium", "cypress", "playwright", "בדיקות תוכנה"],
    # product / design / management
    "Product Management": ["product manager", "product management", "ניהול מוצר", "מנהל מוצר"],
    "UX/UI": ["ux", "ui", "figma", "sketch", "user experience", "חווית משתמש"],
    "Agile/Scrum": ["agile", "scrum", "kanban", "jira"],
    "Project Management": ["project manager", "project management", "ניהול פרויקטים"],
    "People Management": ["team lead", "engineering manager", "ניהול צוות", "ראש צוות", "מוביל צוות"],
    # marketing / bizdev / other common
    "Digital Marketing": ["digital marketing", "seo", "sem", "ppc", "שיווק דיגיטלי"],
    "Sales": ["sales", "account executive", "מכירות"],
    "Customer Success": ["customer success", "csm", "הצלחת לקוחות"],
    "Finance": ["finance", "accounting", "fp&a", "כספים", "הנהלת חשבונות"],
    "Excel": ["excel", "אקסל"],
}

# Seniority keywords -> canonical level (checked in priority order)
SENIORITY_MARKERS: list[tuple[str, list[str]]] = [
    ("director", ["director", "vice president", "head of", "cto", "chief", "סמנכ", "מנהל בכיר"]),
    ("manager", ["engineering manager", "r&d manager", "group manager", "מנהל פיתוח", "מנהל קבוצה"]),
    ("senior", ["senior", "בכיר", "בכירה"]),
    ("lead", ["team lead", "team leader", "tech lead", "lead", "leader", "principal",
              "staff engineer", "architect", "ארכיטקט", "ראש צוות", "מוביל צוות"]),
    ("junior", ["junior", "entry level", "ג'וניור", "מתחיל"]),
    ("intern", ["intern", "internship", "student", "סטודנט", "מתמחה", "התמחות"]),
]

# Common job-title cores to detect
TITLE_PATTERNS: list[str] = [
    "software engineer", "backend engineer", "frontend engineer", "full stack engineer",
    "fullstack engineer", "data engineer", "data scientist", "data analyst",
    "machine learning engineer", "ml engineer", "devops engineer", "sre",
    "qa engineer", "automation engineer", "security engineer", "product manager",
    "project manager", "engineering manager", "team lead", "ui/ux designer",
    "product designer", "mobile developer", "android developer", "ios developer",
    "cloud engineer", "platform engineer", "solutions architect", "research engineer",
    "business analyst", "bi developer", "algorithm engineer", "embedded engineer",
    "מהנדס תוכנה", "מפתח תוכנה", "מפתח backend", "מפתח frontend", "מפתח fullstack",
    "מדען נתונים", "מהנדס נתונים", "מנהל מוצר", "מנהל פרויקטים", "מהנדס devops",
]

LANGUAGE_MARKERS: dict[str, list[str]] = {
    "Hebrew": ["hebrew", "עברית"],
    "English": ["english", "אנגלית"],
    "Arabic": ["arabic", "ערבית"],
    "Russian": ["russian", "רוסית"],
    "French": ["french", "צרפתית"],
    "Spanish": ["spanish", "ספרדית"],
    "German": ["german", "גרמנית"],
}
