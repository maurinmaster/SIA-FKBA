# Arquivo: Dockerfile (na raiz do projeto)

# Imagem base Python
FROM python:3.12-slim

# Definir variáveis de ambiente básicas
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV DJANGO_SETTINGS_MODULE fkba_platform.settings
ENV PATH="/usr/src/app/venv/bin:$PATH"

# Instalar dependências do sistema (para Gunicorn)
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    libpq-dev \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Criar e definir o diretório de trabalho
WORKDIR /usr/src/app

# Criar um ambiente virtual (boas práticas)
RUN python -m venv venv
# Instalar dependências
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo o código-fonte
COPY . .

# Coletar arquivos estáticos (usando o caminho definido em settings.py)
# Isso criará a pasta 'staticfiles_prod' dentro do contêiner
RUN python manage.py collectstatic --noinput

# O contêiner expõe a porta 8000 para comunicação interna
EXPOSE 8000

# Comando para iniciar o servidor Gunicorn
# 'fkba_platform.wsgi' é o caminho para sua aplicação WSGI
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "fkba_platform.wsgi:application"]