# Arquivo: Dockerfile (na raiz do projeto)

# Imagem base Python
FROM python:3.12-slim

# Definir variáveis de ambiente básicas
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV DJANGO_SETTINGS_MODULE fkba_platform.settings

# Criar e definir o diretório de trabalho
WORKDIR /usr/src/app

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    libpq-dev \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements.txt
COPY requirements.txt .

# PASSO CRÍTICO: Instalar dependências DIRETAMENTE no sistema do contêiner.
# O Gunicorn será instalado no PATH padrão do sistema.
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo o código-fonte restante
COPY . .

# Criar o diretório para o banco de dados SQLite
RUN mkdir -p /usr/src/app/data

# Coletar arquivos estáticos
RUN python manage.py collectstatic --noinput

# O contêiner expõe a porta 8000 para comunicação interna
EXPOSE 8000

# COMANDO FINAL CORRIGIDO: Agora o Gunicorn estará no PATH e acessível.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "fkba_platform.wsgi:application"]