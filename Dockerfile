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
# Certifique-se de que o pip está usando o venv:
RUN venv/bin/pip install --no-cache-dir -r requirements.txt 

# Copiar todo o código-fonte
COPY . .

# Criar o diretório para o banco de dados SQLite
RUN mkdir -p /usr/src/app/data

# Coletar arquivos estáticos (usando o caminho definido em settings.py)
# Certifique-se de que o comando é executado com o python do venv
RUN venv/bin/python manage.py collectstatic --noinput

# O contêiner expõe a porta 8000 para comunicação interna
EXPOSE 8000

# CORREÇÃO CRUCIAL: Usar o comando shell para ativar o venv e executar o Gunicorn.
# Alternativa 1: Rodar o Gunicorn diretamente pelo caminho absoluto do venv
# CMD ["/usr/src/app/venv/bin/gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "fkba_platform.wsgi:application"]

# Alternativa 2 (Recomendada para ambientes virtuais): Usar o shell e o executável do venv
CMD ["/bin/bash", "-c", "source venv/bin/activate && gunicorn --bind 0.0.0.0:8000 --workers 3 fkba_platform.wsgi:application"]