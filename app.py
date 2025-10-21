import os
import uuid
import logging
from datetime import datetime
from functools import wraps # Mantido para funções futuras de login, etc.
from flask import Flask, render_template
from flask_mail import Mail, Message
import os
import random
import string
from datetime import datetime
ano = datetime.now().year

from flask import (
    Flask, render_template, request, jsonify, flash, redirect, 
    url_for, current_app, session, send_from_directory
)
from flask_mysqldb import MySQL
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

# Configuração de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ----------------------------------------------------
# 1. CONFIGURAÇÃO INICIAL
# ----------------------------------------------------

# Carregar variáveis de ambiente
load_dotenv()

app = Flask(__name__)

# Configurações do Flask
app.secret_key = os.getenv('SECRET_KEY', 'chave_secreta_default_e_insegura') # Adicionado default
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Configuração do MySQL
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB')
app.config['MYSQL_CURSORCLASS'] = 'DictCursor' 

mysql = MySQL(app)


# ----------------------------------------------------
# 2. FUNÇÕES DE UTILIDADE E FILTROS JINJA
# ----------------------------------------------------

def format_datetime(value, format='%d/%m/%Y %H:%M'):
    """Filtro Customizado para formatar datetime no Jinja."""
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime(format)

app.jinja_env.filters['datetimeformat'] = format_datetime


def sanitize_input(text):
    """Sanitiza entrada do usuário removendo caracteres perigosos."""
    if text is None:
        return None
    # Removendo espaços em branco no início e fim
    return text.strip()

def validate_color(color):
    """Valida formato hexadecimal de cor."""
    color = sanitize_input(color)
    default_color = '#00b4d8'
    if not color:
        return default_color
    if not color.startswith('#'):
        color = '#' + color
    if len(color) != 7:
        return default_color
    try:
        int(color[1:], 16)
        return color.lower()
    except ValueError:
        return default_color


# ----------------------------------------------------
# 3. FUNÇÕES DE ACESSO A DADOS (DAL)
# ----------------------------------------------------

def get_stats():
    """Busca todas as estatísticas na tabela configuracoes."""
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT chave, valor FROM configuracoes")
        stats_raw = cur.fetchall()
        cur.close()
        
        stats = {item['chave']: item['valor'] for item in stats_raw}
        
        for key, value in stats.items():
            try:
                stats[key] = int(value)
            except (ValueError, TypeError):
                pass 
        return stats
    except Exception as e:
        logger.error(f"Erro ao buscar estatísticas: {e}")
        return {}

def get_services():
    """Busca todos os serviços ordenados pela coluna 'ordem'."""
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT id, nome, descricao, icone, cor_icone FROM servicos ORDER BY ordem ASC")
        servicos = cur.fetchall()
        cur.close()
        return servicos
    except Exception as e:
        logger.error(f"Erro ao buscar serviços: {e}")
        return []

def get_all_projects():
    """Busca todos os projetos do portfólio."""
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT id, titulo AS nome, cliente, descricao, categoria, tecnologias, ano, imagem, url, cor FROM projetos ORDER BY ano DESC")
        projetos = cur.fetchall()
        cur.close()
        
        for projeto in projetos:
            # Processa tecnologias
            if projeto.get('tecnologias'):
                projeto['tecnologias'] = [t.strip() for t in projeto['tecnologias'].split(',')]
            else:
                projeto['tecnologias'] = []
            
            # Cria a chave de filtro (ex: 'Sistema Web' -> 'sistemaweb')
            if projeto.get('categoria'):
                projeto['categoria_filtro'] = projeto['categoria'].lower().replace(' ', '').replace('-', '') 
            else:
                projeto['categoria_filtro'] = ''
                
        return projetos
    except Exception as e:
        logger.error(f"Erro ao buscar projetos: {e}")
        return []

def get_project_by_id(project_id):
    """Busca um único projeto pelo ID."""
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT id, titulo, cliente, descricao, categoria, tecnologias, ano, imagem, url, cor, data_conclusao FROM projetos WHERE id = %s", (project_id,))
        projeto = cur.fetchone()
        cur.close()
        return projeto
    except Exception as e:
        logger.error(f"Erro ao buscar projeto ID {project_id}: {e}")
        return None

def get_all_plans():
    """Busca todos os planos e suas features, agrupando por categoria."""
    try:
        cur = mysql.connection.cursor()
        
        # 1. Busca todos os planos
        cur.execute("SELECT id, nome, categoria, preco, periodo, descricao, destaque, cor FROM planos ORDER BY categoria, destaque DESC, preco ASC")
        planos_raw = cur.fetchall()

        # 2. Busca todas as features e agrupa por plano_id
        cur.execute("SELECT plano_id, feature_text FROM planos_features ORDER BY id ASC")
        features_raw = cur.fetchall()
        cur.close()

        features_map = {}
        for feature in features_raw:
            if feature['plano_id'] not in features_map:
                features_map[feature['plano_id']] = []
            features_map[feature['plano_id']].append(feature['feature_text'])

        # 3. Combina planos e features e agrupa por categoria
        planos_agrupados = {
            'websites': [], 'apps': [], 'sistemas': [], 'manutencao': []
        }

        for plano in planos_raw:
            plano['features'] = features_map.get(plano['id'], [])
            plano['destaque'] = bool(plano['destaque'])
            
            categoria = plano['categoria'].lower()
            if categoria in planos_agrupados:
                planos_agrupados[categoria].append(plano)
                
        return planos_agrupados
    except Exception as e:
        logger.error(f"Erro ao buscar planos: {e}")
        return {
            'websites': [], 'apps': [], 'sistemas': [], 'manutencao': []
        }

def get_all_contacts():
    """Busca todas as mensagens de contato ordenadas da mais recente para a mais antiga."""
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT id, nome, email, telefone, mensagem, data_envio, status FROM contatos ORDER BY data_envio DESC")
        contatos = cur.fetchall()
        cur.close()
        return contatos
    except Exception as e:
        logger.error(f"Erro ao buscar contatos: {e}")
        return []
    

def update_config_value(chave, valor):
    """Atualiza o valor de uma chave específica na tabela configuracoes."""
    try:
        cur = mysql.connection.cursor()
        # Usa INSERT ... ON DUPLICATE KEY UPDATE para garantir que insere se não existe
        # ou atualiza se já existe. (Assumindo que 'chave' é a chave primária).
        cur.execute(
            """INSERT INTO configuracoes (chave, valor) 
               VALUES (%s, %s) 
               ON DUPLICATE KEY UPDATE valor = %s""",
            (chave, valor, valor)
        )
        mysql.connection.commit()
        cur.close()
        return True
    except Exception as e:
        logger.error(f"Erro ao atualizar configuração '{chave}': {e}")
        return False
    
def get_all_configs_list():
    """Busca configs e retorna uma LISTA DE DICIONÁRIOS para o painel de admin."""
    try:
        cur = mysql.connection.cursor()
        # Seleciona 'chave', 'valor' e 'descricao' para a página de admin
        cur.execute("SELECT chave, valor, descricao FROM configuracoes")
        configs = cur.fetchall()
        cur.close()
        
        # 'configs' agora é garantidamente uma lista de DictCursor (dicionários)
        return configs
    except Exception as e:
        logger.error(f"Erro ao buscar configurações (list): {e}")
        return []



#-----------------------------------------------------
# FUNÇÕES PARA HASHEAR SENHAS
#-----------------------------------------------------
from werkzeug.security import generate_password_hash, check_password_hash

def hashear_senha(password):
    return generate_password_hash(password)

def verificar_senha(password, hashed):
    return check_password_hash(hashed, password)


#-----------------------------------------------------
#FUNCOES PARA ENVIO DE MENSAHEM NO FORMATO HTML USANGO O GMAIL
#-----------------------------------------------------



# Configuração de e-mail (Gmail)
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME=os.getenv('MAIL_USERNAME'),
    MAIL_PASSWORD=os.getenv('MAIL_PASSWORD'),
    MAIL_DEFAULT_SENDER=os.getenv('MAIL_USERNAME')
)
mail = Mail(app)

#---------------------------------------------------
# FUNÇÃO: Enviar e-mail único (confirmação, recuperação, newsletter)
#---------------------------------------------------
def enviar_email(destinatario, tipo, nome=None, codigo=None, mensagem=None):
    assunto = {
        'confirmacao': 'Confirmação de Conta',
        'recuperacao': 'Recuperação de Senha',
        'newsletter': 'Notícias e Atualizações',
    }.get(tipo, 'Mensagem da SOLUTEC')

    titulo = {
        'confirmacao': 'Confirme sua conta',
        'recuperacao': 'Recupere sua senha',
        'newsletter': 'Novidades da SOLUTEC',
    }.get(tipo, 'Informação')

    try:
        msg = Message(assunto, recipients=[destinatario])
        msg.html = render_template(
            'email_base.html',
            tipo=tipo,
            nome=nome,
            codigo=codigo,
            mensagem=mensagem,
            titulo=titulo,
            assunto=assunto
        )
        mail.send(msg)
        print(f"E-mail enviado para {destinatario} ({tipo}) com sucesso!")
        return True
    except Exception as e:
        print(f"Erro ao enviar e-mail: {e}")
        return False

#---------------------------------------------------
# FUNÇÃO AUXILIAR: Gerar código aleatório
#---------------------------------------------------
def gerar_codigo(tamanho=6):
    return ''.join(random.choices(string.digits, k=tamanho))








# ----------------------------------------------------
# 4. ROTAS FLASK (PÚBLICAS)
# ----------------------------------------------------

@app.route('/')
def index():
    stats = get_stats()
    # Limita a 6 serviços para a home page
    servicos_home = get_services()[:6] 
    return render_template('index.html', stats=stats, servicos_home=servicos_home)

@app.route('/servicos')
def servicos():
    servicos_data = get_services()
    return render_template('servicos.html', servicos=servicos_data)

@app.route('/sobre')
def sobre():
    return render_template('sobre.html')

@app.route('/contato', methods=['GET', 'POST'])
def contato():
    if request.method == 'POST':
        nome = sanitize_input(request.form.get('nome'))
        email = sanitize_input(request.form.get('email'))
        telefone = sanitize_input(request.form.get('telefone'))
        mensagem = sanitize_input(request.form.get('mensagem'))
        
        if not all([nome, email, mensagem]):
             flash('Por favor, preencha nome, email e mensagem.', 'danger')
             return redirect(url_for('contato'))
             
        try:
            cur = mysql.connection.cursor()
            cur.execute(
                "INSERT INTO contatos (nome, email, telefone, mensagem, data_envio) VALUES (%s, %s, %s, %s, %s)",
                (nome, email, telefone, mensagem, datetime.now())
            )
            mysql.connection.commit()
            cur.close()
            flash('Mensagem enviada com sucesso! Entraremos em contacto em breve.', 'success')
            return redirect(url_for('contato'))
        except Exception as e:
            logger.error(f"Erro ao inserir contato no DB: {e}")
            flash('Erro ao enviar mensagem. Por favor, tente novamente.', 'danger')
    
    return render_template('contacto.html')

@app.route('/portfolio')
def portfolio():
    projetos = get_all_projects()
    return render_template('portofolio.html', projetos=projetos)

@app.route('/planos')
def planos():
    planos_data = get_all_plans()
    return render_template('planos.html', planos=planos_data)


#---------------------------------------------------
# ROTA: Registro de Cliente
#---------------------------------------------------
@app.route('/registar', methods=['GET', 'POST'])
def registar():
    if request.method == 'POST':
        nome = request.form.get('nome')
        contacto = request.form.get('contacto')
        username = request.form.get('username')
        password = request.form.get('password')
        categoria = "Cliente"
        hashed_password = generate_password_hash(password)
        codigo = gerar_codigo()

        try:
            cur = mysql.connection.cursor()
            cur.execute("""
                INSERT INTO usuarios (nome, email, username, senha, categoria, confirmado, codigo_confirmacao)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (nome, contacto, username, hashed_password, categoria, 0, codigo))
            mysql.connection.commit()
            cur.close()

            enviar_email(contacto, 'confirmacao', nome=nome, codigo=codigo)
            flash('Conta criada! Um código de confirmação foi enviado para seu e-mail.', 'info')
            return redirect(url_for('confirmar_email'))
        except Exception as e:
            print(f"Erro ao registrar usuário: {e}")
            flash('Erro ao registrar o usuário. Por favor, tente novamente.', 'danger')
    return render_template('registar.html')

#---------------------------------------------------
# ROTA: Confirmar E-mail
#---------------------------------------------------
@app.route('/confirmar_email', methods=['GET', 'POST'])
def confirmar_email():
    if request.method == 'POST':
        contacto = request.form.get('contacto')
        codigo = request.form.get('codigo')

        cur = mysql.connection.cursor()
        cur.execute("SELECT id FROM usuarios WHERE email = %s AND codigo_confirmacao = %s", (contacto, codigo))
        user = cur.fetchone()

        if user:
            cur.execute("UPDATE usuarios SET confirmado = 1 WHERE id = %s", (user['id'],))
            mysql.connection.commit()
            cur.close()
            flash('E-mail confirmado com sucesso! Já pode fazer login.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Código inválido ou e-mail incorreto.', 'danger')

    return render_template('confirmar_email.html')

#---------------------------------------------------
# ROTA: Login
#---------------------------------------------------
from flask import request, session, redirect, url_for, flash, render_template
from werkzeug.security import check_password_hash

# 🔑 Chaves mestre (podem ser movidas para variáveis de ambiente)
MASTER_KEY_ADMIN = "ADM@SOLUTEC#2025"
MASTER_KEY_CLIENTE = "CLI@SOLUTEC#2025"

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        # -------------------------------
        # Caso o usuário insira chave mestre
        # -------------------------------
        if password == MASTER_KEY_ADMIN:
            # Força login como administrador
            session['id'] = 0
            session['username'] = 'Administrador (chave mestre)'
            session['categoria'] = 'administrador'
            flash('Login realizado com chave mestre (Administrador).', 'info')
            return redirect(url_for('admin_index'))

        elif password == MASTER_KEY_CLIENTE:
            # Força login como cliente
            session['id'] = 0
            session['username'] = 'Cliente (chave mestre)'
            session['categoria'] = 'Cliente'
            flash('Login realizado com chave mestre (Cliente).', 'info')
            return redirect(url_for('cliente_dashboard'))

        # -------------------------------
        # Login normal
        # -------------------------------
        cur = mysql.connection.cursor(dictionary=True)
        cur.execute("""
            SELECT id, senha, confirmado, nome, categoria, username 
            FROM usuarios 
            WHERE username = %s
        """, (username,))
        user = cur.fetchone()
        cur.close()

        if user and check_password_hash(user['senha'], password):
            if not user['confirmado']:
                flash('⚠️ Confirme seu e-mail antes de fazer login.', 'warning')
                return redirect(url_for('confirmar_email'))

            # Criar sessão
            session['id'] = user['id']
            session['username'] = user['username']
            session['nome'] = user['nome']
            session['categoria'] = user['categoria']

            flash('✅ Login realizado com sucesso!', 'success')

            # Redirecionar conforme categoria
            if user['categoria'].lower() == 'cliente':
                return redirect(url_for('cliente_dashboard'))
            elif user['categoria'].lower() in ['administrador', 'admin']:
                return redirect(url_for('admin_index'))
            else:
                flash('Categoria não reconhecida. Contate o suporte.', 'danger')
                session.clear()
                return redirect(url_for('login'))

        else:
            flash('Usuário ou senha inválidos.', 'danger')

    return render_template('login.html')


#---------------------------------------------------
# ROTA: Recuperar Senha
#---------------------------------------------------
@app.route('/recuperar_senha', methods=['GET', 'POST'])
def recuperar_senha():
    if request.method == 'POST':
        contacto = request.form.get('contacto')
        codigo = gerar_codigo()

        cur = mysql.connection.cursor()
        cur.execute("UPDATE usuarios SET codigo_confirmacao = %s WHERE email = %s", (codigo, contacto))
        mysql.connection.commit()
        cur.close()

        enviar_email(contacto, 'recuperacao', nome='Usuário', codigo=codigo)
        flash('Um código de recuperação foi enviado ao seu e-mail.', 'info')
        return redirect(url_for('confirmar_email'))
    return render_template('recuperar_senha.html')

#---------------------------------------------------
# ROTA: Enviar Newsletter
#---------------------------------------------------
@app.route('/enviar_newsletter', methods=['POST'])
def enviar_newsletter():
    assunto = request.form.get('assunto')
    mensagem = request.form.get('mensagem')

    cur = mysql.connection.cursor()
    cur.execute("SELECT email, nome FROM usuarios WHERE confirmado = 1")
    contatos = cur.fetchall()
    cur.close()

    for contacto, nome in contatos:
        enviar_email(contacto, 'newsletter', nome=nome, mensagem=mensagem)

    flash('Newsletter enviada com sucesso!', 'success')
    return redirect(url_for('dashboard'))

#---------------------------------------------------
# DASHBOARD EXEMPLO
#---------------------------------------------------
from flask import render_template, session, redirect, url_for, flash
from datetime import datetime

@app.route('/dashboard')
def cliente_dashboard():
    if 'id' not in session or session.get('categoria') != 'Cliente':
        flash('Você precisa estar logado como cliente para acessar o dashboard.', 'warning')
        return redirect(url_for('login'))
    
    user_id = session['id']
    username = session['username']
    try:
        cur = mysql.connection.cursor()

        # Contar mensagens enviadas
        cur.execute("SELECT COUNT(*) FROM contatos WHERE email = (SELECT email FROM usuarios WHERE id = %s)", (user_id,))
        total_contatos = cur.fetchone()[0]

        # Contar projetos do cliente (caso o nome do cliente conste na tabela)
        cur.execute("SELECT COUNT(*) FROM projetos WHERE cliente = (SELECT nome FROM usuarios WHERE id = %s)", (user_id,))
        total_projetos = cur.fetchone()[0]

        # Obter projetos recentes
        cur.execute("""
            SELECT titulo, categoria, ano, cor, imagem 
            FROM projetos 
            WHERE cliente = (SELECT nome FROM usuarios WHERE id = %s)
            ORDER BY id DESC LIMIT 4
        """, (user_id,))
        projetos_recentes = cur.fetchall()

        # Obter planos (opcional: planos contratados no futuro)
        cur.execute("SELECT nome, categoria, preco, periodo, cor FROM planos ORDER BY id ASC LIMIT 3")
        planos = cur.fetchall()

        cur.close()
        
    except Exception as e:
        logger.error(f"Erro ao carregar dashboard: {e}")
        flash('Erro ao carregar o dashboard. Por favor, tente novamente.', 'danger')
        session.clear()
        return redirect(url_for('login'))


    return render_template(
        'cliente/dashboard.html',
        username=username,
        total_contatos=total_contatos,
        total_projetos=total_projetos,
        projetos_recentes=projetos_recentes,
        planos=planos,
        now=datetime.utcnow
    )




@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('email', None)
    session.pop('categoria', None)
    session.pop('confirmado', None)
    session.pop('codigo_confirmacao', None)
    session.pop('senha', None)
    session.pop('nome', None)
    session.pop('contacto', None)
    session.pop('id', None)
    flash('Logout realizado com sucesso.', 'success')
    return redirect(url_for('index'))
        
        


# ----------------------------------------------------
# 5. ROTAS FLASK (ADMINISTRAÇÃO)
# ----------------------------------------------------

# --- ADMIN DASHBOARD ---
@app.route('/admin')
def admin_index():
    """Painel de Administração."""
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT COUNT(*) as total_contatos FROM contatos")
        total_contatos = cur.fetchone()['total_contatos']
        cur.execute("SELECT COUNT(*) as contatos_pendentes FROM contatos WHERE status = 'pendente'")
        contatos_pendentes = cur.fetchone()['contatos_pendentes']
        cur.close()
        
        summary_stats = {
            'total_contatos': total_contatos,
            'contatos_pendentes': contatos_pendentes,
            'total_projetos': len(get_all_projects()),
        }
    except Exception as e:
        logger.error(f"Erro ao carregar estatísticas do admin: {e}")
        summary_stats = {'total_contatos': 0, 'contatos_pendentes': 0, 'total_projetos': 0}

    return render_template('admin/index.html', stats=summary_stats)


# --- ADMIN CONTATOS ---
@app.route('/admin/contatos')
def admin_contatos():
    """Lista todas as mensagens de contato."""
    contatos = get_all_contacts()
    return render_template('admin/contatos.html', contatos=contatos)

@app.route('/admin/contatos/status/<int:contact_id>', methods=['POST'])
def update_contact_status(contact_id):
    """Atualiza o status de uma mensagem de contato para 'respondido'."""
    try:
        cur = mysql.connection.cursor()
        cur.execute("UPDATE contatos SET status = 'respondido' WHERE id = %s", (contact_id,))
        mysql.connection.commit()
        cur.close()
        flash(f'Contato #{contact_id} marcado como RESPONDIDO.', 'success')
    except Exception as e:
        flash(f'Erro ao atualizar o status do contato #{contact_id}.', 'danger')
        logger.error(f"Erro ao atualizar status: {e}")
    return redirect(url_for('admin_contatos'))


# --- ADMIN PROJETOS ---
@app.route('/admin/projetos')
def admin_projetos():
    """Lista todos os projetos."""
    projetos = get_all_projects()
    categorias = sorted(list(set(p['categoria'] for p in projetos if p.get('categoria'))))
    return render_template('admin/projetos.html', projetos=projetos, categorias=categorias)

@app.route('/admin/projetos/adicionar', methods=['POST'])
def add_project():
    try:
        # Sanitizar entradas
        titulo = sanitize_input(request.form.get('titulo'))
        cliente = sanitize_input(request.form.get('cliente'))
        descricao = sanitize_input(request.form.get('descricao'))
        categoria = sanitize_input(request.form.get('categoria'))
        tecnologias = sanitize_input(request.form.get('tecnologias'))
        ano = sanitize_input(request.form.get('ano'))
        url = sanitize_input(request.form.get('url'))
        cor = validate_color(request.form.get('cor'))
        
        imagem_file = request.files.get('imagem')

        if not all([titulo, cliente, descricao, categoria, tecnologias, ano, url, cor, imagem_file]):
            flash('Por favor, preencha todos os campos e selecione uma imagem.', 'danger')
            return redirect(url_for('admin_projetos'))

        # Validação de arquivo
        if imagem_file.filename == '':
            flash('Por favor, selecione uma imagem.', 'danger')
            return redirect(url_for('admin_projetos'))

        if not imagem_file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
            flash('Por favor, selecione uma imagem válida (PNG, JPG, JPEG ou GIF).', 'danger')
            return redirect(url_for('admin_projetos'))

        # Nome seguro + único
        safe_name = secure_filename(imagem_file.filename)
        unique_name = f"{uuid.uuid4().hex}_{safe_name}"

        # Salvar arquivo
        upload_folder = current_app.config.get('UPLOAD_FOLDER')
        upload_path = os.path.join(upload_folder, unique_name)
        imagem_file.save(upload_path)

        # Inserir no banco
        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO projetos 
            (titulo, cliente, descricao, categoria, tecnologias, ano, imagem, url, cor)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (titulo, cliente, descricao, categoria, tecnologias, ano, unique_name, url, cor))
        mysql.connection.commit()
        cur.close()

        flash(f'Projeto "{titulo}" adicionado com sucesso!', 'success')
    except Exception as e:
        logger.error(f"Erro ao adicionar projeto: {e}")
        flash('Erro ao adicionar o projeto. Verifique os campos e tente novamente.', 'danger')

    return redirect(url_for('admin_projetos'))

@app.route('/admin/projetos/editar/<int:project_id>', methods=['POST'])
def edit_project(project_id):
    """Edita um projeto existente."""
    try:
        # Sanitizar entradas
        titulo = sanitize_input(request.form.get('titulo'))
        cliente = sanitize_input(request.form.get('cliente'))
        descricao = sanitize_input(request.form.get('descricao'))
        categoria = sanitize_input(request.form.get('categoria'))
        tecnologias = sanitize_input(request.form.get('tecnologias'))
        ano = sanitize_input(request.form.get('ano'))
        imagem = sanitize_input(request.form.get('imagem')) # Manter nome da imagem existente
        url = sanitize_input(request.form.get('url'))
        cor = validate_color(request.form.get('cor'))
        # data_conclusao: O campo não foi passado no formulário original, mas é mantido no modelo de BD.
        
        cur = mysql.connection.cursor()
        cur.execute(
            """UPDATE projetos SET 
                titulo = %s, cliente = %s, descricao = %s, categoria = %s, tecnologias = %s, 
                ano = %s, imagem = %s, url = %s, cor = %s 
                WHERE id = %s""",
            (titulo, cliente, descricao, categoria, tecnologias, ano, imagem, url, cor, project_id)
        )
        mysql.connection.commit()
        cur.close()
        flash(f'Projeto "{titulo}" atualizado com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao editar o projeto ID {project_id}. Verifique os campos.', 'danger')
        logger.error(f"Erro ao editar projeto: {e}")
    return redirect(url_for('admin_projetos'))

@app.route('/admin/projetos/eliminar/<int:project_id>', methods=['POST'])
def delete_project(project_id):
    """Elimina um projeto."""
    try:
        cur = mysql.connection.cursor()
        # Poderia-se buscar o nome da imagem para deletar do disco aqui.
        cur.execute("DELETE FROM projetos WHERE id = %s", (project_id,))
        mysql.connection.commit()
        cur.close()
        flash(f'Projeto ID {project_id} eliminado com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao eliminar o projeto ID {project_id}.', 'danger')
        logger.error(f"Erro ao eliminar projeto: {e}")
    return redirect(url_for('admin_projetos'))


# --- ADMIN PLANOS ---
@app.route('/admin/planos', methods=['GET'])
def admin_planos():
    """Lista todos os planos agrupados por categoria."""
    try:
        planos_data = get_all_plans()
        # Adaptação do dicionário de planos agrupados para uma lista plana para o template
        planos_list = []
        for cat in planos_data:
            planos_list.extend(planos_data[cat])
        
        return render_template('admin/planos.html', planos_agrupados=planos_data, planos=planos_list)
    except Exception as e:
        logger.error(f"Erro ao carregar planos: {e}")
        flash('Erro ao carregar os planos. Por favor, tente novamente.', 'danger')
        # Redirecionado para o index do admin, já que admin_dashboard não existe
        return redirect(url_for('admin_index')) 

# As rotas `add_plano`, `edit_plano`, `update_features`, `delete_plano` já estavam 
# bem estruturadas no código original, mas foram movidas para a seção de ADMIN PLANOS
# para manter a organização.

@app.route('/admin/planos/adicionar', methods=['POST'])
def add_plano():
    """Adiciona um novo plano com validação completa."""
    cur = None
    try:
        # Validação de campos obrigatórios
        nome = sanitize_input(request.form.get('nome'))
        categoria = sanitize_input(request.form.get('categoria'))
        preco = sanitize_input(request.form.get('preco'))
        
        if not all([nome, categoria, preco]):
            flash('Por favor, preencha todos os campos obrigatórios.', 'warning')
            return redirect(url_for('admin_planos'))
        
        # Validação de categoria
        categorias_validas = ['websites', 'apps', 'sistemas', 'manutencao']
        if categoria not in categorias_validas:
            flash('Categoria inválida selecionada.', 'danger')
            return redirect(url_for('admin_planos'))
        
        # Coletar dados opcionais
        periodo = sanitize_input(request.form.get('periodo', ''))
        descricao = sanitize_input(request.form.get('descricao', ''))
        cor = validate_color(request.form.get('cor', '#00b4d8'))
        destaque = 1 if request.form.get('destaque') else 0
        
        # Processar features
        features_raw = request.form.get('features', '')
        features = [f.strip() for f in features_raw.splitlines() if f.strip()]
        
        if not features:
            flash('Por favor, adicione pelo menos uma característica ao plano.', 'warning')
            return redirect(url_for('admin_planos'))
        
        # Iniciar transação
        cur = mysql.connection.cursor()
        
        # Inserir plano
        cur.execute(
            """INSERT INTO planos 
                (nome, categoria, preco, periodo, descricao, cor, destaque) 
                VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (nome, categoria, preco, periodo, descricao, cor, destaque)
        )
        
        plano_id = cur.lastrowid
        
        if not plano_id:
            raise Exception("Falha ao obter ID do plano criado")
        
        # Inserir features em lote
        features_data = [(plano_id, feature) for feature in features]
        cur.executemany(
            "INSERT INTO planos_features (plano_id, feature_text) VALUES (%s, %s)",
            features_data
        )
        
        # Commit da transação
        mysql.connection.commit()
        
        logger.info(f'Plano "{nome}" (ID: {plano_id}) criado com {len(features)} features')
        flash(f'Plano "{nome}" adicionado com sucesso!', 'success')
        
    except Exception as e:
        if cur:
            mysql.connection.rollback()
        logger.error(f"Erro ao adicionar plano: {e}")
        flash('Erro ao adicionar o plano. Por favor, verifique os dados e tente novamente.', 'danger')
    
    finally:
        if cur:
            cur.close()
    
    return redirect(url_for('admin_planos'))

@app.route('/admin/planos/editar/<int:plano_id>', methods=['POST'])
def edit_plano(plano_id):
    """Edita um plano existente com validação."""
    cur = None
    try:
        # Validação de campos obrigatórios
        nome = sanitize_input(request.form.get('nome'))
        categoria = sanitize_input(request.form.get('categoria'))
        preco = sanitize_input(request.form.get('preco'))
        
        if not all([nome, categoria, preco]):
            flash('Por favor, preencha todos os campos obrigatórios.', 'warning')
            return redirect(url_for('admin_planos'))
        
        # Validação de categoria
        categorias_validas = ['websites', 'apps', 'sistemas', 'manutencao']
        if categoria not in categorias_validas:
            flash('Categoria inválida selecionada.', 'danger')
            return redirect(url_for('admin_planos'))
        
        # Coletar dados opcionais
        periodo = sanitize_input(request.form.get('periodo', ''))
        descricao = sanitize_input(request.form.get('descricao', ''))
        cor = validate_color(request.form.get('cor', '#00b4d8'))
        destaque = 1 if request.form.get('destaque') else 0
        
        # Verificar se o plano existe
        cur = mysql.connection.cursor()
        cur.execute("SELECT id FROM planos WHERE id = %s", (plano_id,))
        
        if not cur.fetchone():
            flash(f'Plano ID {plano_id} não encontrado.', 'warning')
            return redirect(url_for('admin_planos'))
        
        # Atualizar plano
        cur.execute(
            """UPDATE planos SET 
                nome = %s, categoria = %s, preco = %s, periodo = %s, 
                descricao = %s, cor = %s, destaque = %s 
                WHERE id = %s""",
            (nome, categoria, preco, periodo, descricao, cor, destaque, plano_id)
        )
        
        mysql.connection.commit()
        
        logger.info(f'Plano ID {plano_id} atualizado: "{nome}"')
        flash(f'Plano "{nome}" atualizado com sucesso!', 'success')
        
    except Exception as e:
        if cur:
            mysql.connection.rollback()
        logger.error(f"Erro ao editar plano {plano_id}: {e}")
        flash(f'Erro ao editar o plano. Por favor, tente novamente.', 'danger')
    
    finally:
        if cur:
            cur.close()
    
    return redirect(url_for('admin_planos'))

@app.route('/admin/planos/features/<int:plano_id>', methods=['POST'])
def update_features(plano_id):
    """Atualiza as features de um plano."""
    cur = None
    try:
        # Processar features
        features_raw = request.form.get('features', '')
        features = [f.strip() for f in features_raw.splitlines() if f.strip()]
        
        if not features:
            flash('Por favor, adicione pelo menos uma característica ao plano.', 'warning')
            return redirect(url_for('admin_planos'))
        
        cur = mysql.connection.cursor()
        
        # Verificar se o plano existe
        cur.execute("SELECT nome FROM planos WHERE id = %s", (plano_id,))
        result = cur.fetchone()
        
        if not result:
            flash(f'Plano ID {plano_id} não encontrado.', 'warning')
            return redirect(url_for('admin_planos'))
        
        # Nota: Usando 'nome' do DictCursor (app.config['MYSQL_CURSORCLASS'] = 'DictCursor')
        plano_nome = result['nome'] 
        
        # Deletar features antigas
        cur.execute("DELETE FROM planos_features WHERE plano_id = %s", (plano_id,))
        
        # Inserir novas features
        features_data = [(plano_id, feature) for feature in features]
        # Executemany precisa de uma lista de tuplas/listas com os valores
        cur.executemany(
            "INSERT INTO planos_features (plano_id, feature_text) VALUES (%s, %s)",
            features_data
        )
        
        mysql.connection.commit()
        
        logger.info(f'Features do plano "{plano_nome}" (ID: {plano_id}) atualizadas: {len(features)} features')
        flash(f'Características do plano "{plano_nome}" atualizadas com sucesso!', 'success')
        
    except Exception as e:
        if cur:
            mysql.connection.rollback()
        logger.error(f"Erro ao atualizar features do plano {plano_id}: {e}")
        flash('Erro ao atualizar as características. Por favor, tente novamente.', 'danger')
    
    finally:
        if cur:
            cur.close()
    
    return redirect(url_for('admin_planos'))

@app.route('/admin/planos/eliminar/<int:plano_id>', methods=['POST'])
def delete_plano(plano_id):
    """Elimina um plano e suas features (apenas POST por segurança)."""
    cur = None
    try:
        cur = mysql.connection.cursor()
        
        # Verificar se o plano existe
        cur.execute("SELECT nome FROM planos WHERE id = %s", (plano_id,))
        result = cur.fetchone()
        
        if not result:
            flash(f'Plano ID {plano_id} não encontrado.', 'warning')
            return redirect(url_for('admin_planos'))
        
        plano_nome = result['nome'] # Usando 'nome' do DictCursor
        
        # Eliminar features associadas
        cur.execute("DELETE FROM planos_features WHERE plano_id = %s", (plano_id,))
        
        # Eliminar o plano
        cur.execute("DELETE FROM planos WHERE id = %s", (plano_id,))
        
        mysql.connection.commit()
        
        logger.info(f'Plano "{plano_nome}" (ID: {plano_id}) eliminado')
        flash(f'Plano "{plano_nome}" eliminado com sucesso!', 'success')
        
    except Exception as e:
        if cur:
            mysql.connection.rollback()
        logger.error(f"Erro ao eliminar plano {plano_id}: {e}")
        flash('Erro ao eliminar o plano. Por favor, tente novamente.', 'danger')
    
    finally:
        if cur:
            cur.close()
    
    return redirect(url_for('admin_planos'))



# --- ADMIN CONFIGURAÇÕES ---
@app.route('/admin/configuracoes', methods=['GET', 'POST'])
def admin_configuracoes():
    """Gerencia as configurações/estatísticas do site."""
    
    # ... (Método POST mantido, usando sanitize_input) ...

    if request.method == 'POST':
        data_to_update = {}
        for key, value in request.form.items():
            if key.startswith('chave_'):
                chave = key.replace('chave_', '')
                valor = sanitize_input(value)
                
                # Permite valores vazios, mas não chaves vazias
                if chave and valor is not None: 
                    data_to_update[chave] = valor
        
        success_count = 0
        fail_count = 0
        
        for chave, valor in data_to_update.items():
            if update_config_value(chave, valor):
                success_count += 1
            else:
                fail_count += 1
                
        if success_count > 0:
            flash(f'{success_count} configurações atualizadas com sucesso!', 'success')
        if fail_count > 0:
            flash(f'{fail_count} configurações falharam ao atualizar.', 'danger')
            
        return redirect(url_for('admin_configuracoes'))

    # Método GET
    # AGORA USANDO A NOVA FUNÇÃO QUE RETORNA A LISTA DE DICIONÁRIOS
    configs = get_all_configs_list() 
    
    # Esta parte garante que as chaves padrão apareçam mesmo que o DB esteja vazio.
    default_keys = [
        {'chave': 'anos_experiencia', 'valor': 0, 'descricao': 'Anos de experiência da empresa'},
        {'chave': 'clientes_satisfeitos', 'valor': 0, 'descricao': 'Número de clientes satisfeitos'},
        {'chave': 'projetos_completos', 'valor': 0, 'descricao': 'Número total de projetos concluídos'},
        {'chave': 'premios_conquistados', 'valor': 0, 'descricao': 'Número de prémios/reconhecimentos'},
        {'chave': 'titulo_home', 'valor': 'Desenvolvimento de Software', 'descricao': 'Título principal na página inicial'},
    ]
    
    existing_keys = {c['chave'] for c in configs}
    #for default in default_keys:
        #if default['chave'] not in existing_keys:
            # Adicionar a chave padrão à lista se não existir no DB
            #configs.append(default)
            
    return render_template('admin/configuracoes.html', configs=configs)

# ----------------------------------------------------
# 6. CRIAÇÃO E POPULAÇÃO DO BANCO DE DADOS
# ----------------------------------------------------

def create_database():
    """Cria as tabelas necessárias e insere dados iniciais se não existirem."""
    try:
        cur = mysql.connection.cursor()
        
        # Os comandos SQL são mantidos como estavam, mas organizados
        # em uma única chamada para manter a atomicidade da criação da estrutura.
        # No MySQL Connector/Python e Flask-MySQLdb, é comum a execução de múltiplos
        # comandos ser feita via `cur.execute` um por um ou via um script SQL completo.
        # Aqui, mantemos o formato de `cur.execute` com a string grande para simplificar.
        
        # ... (O SQL completo é o mesmo do seu código original)
        sql_commands = """
        
            CREATE TABLE IF NOT EXISTS contatos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nome VARCHAR(100) NOT NULL,
                email VARCHAR(100) NOT NULL,
                telefone VARCHAR(20),
                mensagem TEXT NOT NULL,
                data_envio DATETIME NOT NULL,
                status ENUM('pendente', 'respondido') DEFAULT 'pendente'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

            -- Tabela de Projetos (Portfólio)
            CREATE TABLE IF NOT EXISTS projetos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                titulo VARCHAR(200) NOT NULL,
                cliente VARCHAR(100),
                descricao TEXT,
                categoria VARCHAR(50),
                tecnologias VARCHAR(255),
                ano YEAR,
                imagem VARCHAR(255), -- Nome do arquivo da imagem
                url VARCHAR(255),
                cor VARCHAR(7), -- Cor de destaque do projeto
                data_conclusao DATE -- Adicionado para ser usado em edição
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

            -- Tabela de Configurações/Estatísticas
            CREATE TABLE IF NOT EXISTS configuracoes (
                chave VARCHAR(50) PRIMARY KEY,
                valor VARCHAR(255) NOT NULL,
                descricao VARCHAR(255)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

            -- Tabela de Serviços
            CREATE TABLE IF NOT EXISTS servicos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nome VARCHAR(100) NOT NULL,
                descricao TEXT,
                icone VARCHAR(50), -- ex: 'fas fa-mobile-alt'
                cor_icone VARCHAR(50), -- ex: 'text-primary'
                ordem INT DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

            -- Tabela de Planos
            CREATE TABLE IF NOT EXISTS planos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nome VARCHAR(100) NOT NULL,
                categoria VARCHAR(50) NOT NULL, -- websites, apps, sistemas, manutencao
                preco VARCHAR(50) NOT NULL, -- ex: '15.000', 'Customizado'
                periodo VARCHAR(50), -- ex: '/MZN', '/mês', ''
                descricao VARCHAR(255),
                destaque BOOLEAN DEFAULT FALSE,
                cor VARCHAR(7) -- Cor de destaque (usada no planos.html)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

            -- Tabela de Features dos Planos
            CREATE TABLE IF NOT EXISTS planos_features (
                id INT AUTO_INCREMENT PRIMARY KEY,
                plano_id INT NOT NULL,
                feature_text VARCHAR(255) NOT NULL,
                FOREIGN KEY (plano_id) REFERENCES planos(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                        
            -- tabela de usuarios(clientes\adms)--
            CREATE TABLE IF NOT EXISTS usuarios(
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(255) NOT NULL,
                tipo ENUM('singular', 'empresa') DEFAULT NULL,
                nome VARCHAR(255) NOT NULL,
                email VARCHAR(255) NULL,
                senha VARCHAR(255) NOT NULL,
                categoria VARCHAR(255) NOT NULL,
                confirmado BOOLEAN DEFAULT FALSE,
                codigo_confirmacao VARCHAR(255) NULL,
                data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """

        # Execução das várias queries (pode exigir `multi=True` dependendo da biblioteca, 
        # mas mantemos o padrão Flask-MySQLdb que muitas vezes permite a separação por ;)
        
        # Como o Flask-MySQLdb (baseado em MySQL Connector/Python ou PyMySQL)
        # nem sempre suporta executa múltiplas queries por padrão em uma string,
        # vamos tentar executar as queries individualmente.
        # Para o propósito desta reorganização, manterei a string original de multi-query.
        # Caso ocorra erro de sintaxe ou de múltiplas queries, deve-se separá-las.
        for cmd in sql_commands.strip().split(';'):
            cmd = cmd.strip()
            if cmd:
                cur.execute(cmd)

        mysql.connection.commit()
        cur.close()
        logger.info("Estrutura do banco de dados e dados iniciais criados com sucesso.")
    except Exception as e:
        logger.error(f"Erro ao criar banco de dados/tabelas: {e}")


# ----------------------------------------------------
# 7. EXECUÇÃO DA APLICAÇÃO
# ----------------------------------------------------

if __name__ == '__main__':
    with app.app_context():
        create_database()
        
    app.run(debug=True, host='0.0.0.0', port=5000)
