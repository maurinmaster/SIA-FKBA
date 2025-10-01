# Arquivo: Dockerfile (na raiz do projeto)

# Imagem base Python
FROM python:3.12-slim

# Definir variáveis de ambiente básicas
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV DJANGO_SETTINGS_MODULE fkba_platform.settings

# Criar e definir o diretório de trabalho
WORKDIR /usr/src/app

# Instalar dependências do sistema (gcc, python3-dev, libpq-dev, etc.)
# É importante que essas linhas rodem ANTES da instalação do Python
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    libpq-dev \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Criar um ambiente virtual (venv)
RUN python -m venv venv
# Copiar requirements.txt
COPY requirements.txt .

# Instalar dependências DENTRO do venv. 
# Usamos 'venv/bin/pip' para garantir que a instalação ocorra no local certo.
RUN /usr/src/app/venv/bin/pip install --no-cache-dir -r requirements.txt

# Copiar todo o código-fonte restante
COPY . .

# Criar o diretório para o banco de dados SQLite
RUN mkdir -p /usr/src/app/data

# Coletar arquivos estáticos. 
# Usamos 'venv/bin/python' para garantir que o Django use o ambiente com as libs instaladas
RUN /usr/src/app/venv/bin/python manage.py collectstatic --noinput

# O contêiner expõe a porta 8000 para comunicação interna
EXPOSE 8000

# CORREÇÃO TESTE: Usamos o caminho mais provável para o executável do venv
CMD ["/usr/src/app/venv/bin/gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "fkba_platform.wsgi:application"]

# SE O ERRO PERSISTIR: Use esta alternativa (descomente e comente a linha acima)
# CMD ["/usr/src/app/venv/local/bin/gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "fkba_platform.wsgi:application"]