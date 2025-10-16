import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
import requests
from dotenv import load_dotenv

# Carrega .env em dev local (no PythonAnywhere você configurará via Web UI)
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'mudar-esta-chave')
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.environ.get('DATABASE_URL') or 'sqlite:///' + os.path.join(basedir, 'database.sqlite')
app.config['SQLALCHEMY_DATABASE_URI'] = db_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Configs de e-mail
MAILGUN_API_KEY = os.environ.get('MAILGUN_API_KEY')
MAILGUN_DOMAIN = os.environ.get('MAILGUN_DOMAIN')  # ex: "mg.seudominio.com"
SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
MAIL_SENDER = os.environ.get('MAIL_SENDER', f'no-reply@{MAILGUN_DOMAIN}' if MAILGUN_DOMAIN else 'no-reply@example.com')
INSTITUTIONAL_EMAIL = os.environ.get('INSTITUTIONAL_EMAIL')  # coloque seu e-mail institucional aqui

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    prontuario = db.Column(db.String(64))
    nome = db.Column(db.String(120), nullable=False)
    usuario = db.Column(db.String(120), nullable=False)
    mail_to_flaskaulas = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<User {self.nome} ({self.usuario})>'

def send_via_mailgun(to_addr, subject, text):
    if not MAILGUN_API_KEY or not MAILGUN_DOMAIN:
        return False, 'Mailgun não configurado'
    url = f'https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages'
    data = {
        'from': MAIL_SENDER,
        'to': to_addr,
        'subject': subject,
        'text': text
    }
    auth = ('api', MAILGUN_API_KEY)
    r = requests.post(url, auth=auth, data=data, timeout=10)
    if r.status_code in (200, 201):
        return True, 'OK'
    else:
        return False, f'Mailgun erro {r.status_code}: {r.text}'

def send_via_sendgrid(to_addr, subject, text):
    if not SENDGRID_API_KEY:
        return False, 'SendGrid não configurado'
    url = 'https://api.sendgrid.com/v3/mail/send'
    payload = {
        "personalizations": [{"to": [{"email": to_addr}], "subject": subject}],
        "from": {"email": MAIL_SENDER},
        "content": [{"type": "text/plain", "value": text}]
    }
    headers = {
        'Authorization': f'Bearer {SENDGRID_API_KEY}',
        'Content-Type': 'application/json'
    }
    r = requests.post(url, json=payload, headers=headers, timeout=10)
    if r.status_code in (200, 202):
        return True, 'OK'
    else:
        return False, f'SendGrid erro {r.status_code}: {r.text}'

def send_notification_emails(user: User):
    # corpo do e-mail: Prontuário, Nome do aluno, Usuário cadastrado
    body = (
        f'Novo usuário cadastrado\n\n'
        f'Prontuário: {user.prontuario or ""}\n'
        f'Nome do aluno: {user.nome}\n'
        f'Usuário cadastrado: {user.usuario}\n'
    )
    subject = f'Novo cadastro: {user.nome} ({user.usuario})'

    results = {}

    # 1) Sempre enviar para o e-mail institucional, se configurado
    if INSTITUTIONAL_EMAIL:
        ok, msg = (False, 'nenhuma config')
        # tenta Mailgun
        ok, msg = send_via_mailgun(INSTITUTIONAL_EMAIL, subject, body)
        if not ok:
            # tenta SendGrid
            ok2, msg2 = send_via_sendgrid(INSTITUTIONAL_EMAIL, subject, body)
            if ok2:
                ok, msg = True, 'enviado via SendGrid'
            else:
                ok = False
                msg = f'falha Mailgun e SendGrid: {msg} / {msg2}'
        results['institutional'] = (ok, msg)
    else:
        results['institutional'] = (False, 'INSTITUTIONAL_EMAIL não configurado')

    # 2) Se o usuário marcou o checkbox para enviar para flaskaulasweb@zohomail.com
    if user.mail_to_flaskaulas:
        target = 'flaskaulasweb@zohomail.com'
        ok, msg = send_via_mailgun(target, subject, body)
        if not ok:
            ok2, msg2 = send_via_sendgrid(target, subject, body)
            if ok2:
                ok, msg = True, 'enviado via SendGrid'
            else:
                ok = False
                msg = f'falha Mailgun e SendGrid: {msg} / {msg2}'
        results['flaskaulas'] = (ok, msg)
    else:
        results['flaskaulas'] = (False, 'Usuário não solicitou envio')

    return results

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        prontuario = request.form.get('prontuario', '').strip()
        usuario = request.form.get('usuario', '').strip()
        send_mail_box = request.form.get('send_mail') == 'on'

        if not nome or not usuario:
            flash('Preencha pelo menos Nome e Usuário.', 'danger')
            return redirect(url_for('index'))

        # cria e salva
        u = User(prontuario=prontuario, nome=nome, usuario=usuario, mail_to_flaskaulas=send_mail_box)
        db.session.add(u)
        db.session.commit()

        # envia emails (tenta Mailgun -> SendGrid)
        results = send_notification_emails(u)
        # monta mensagem curta para usuário
        ok_inst, msg_inst = results.get('institutional', (False, ''))
        ok_flask, msg_flask = results.get('flaskaulas', (False, ''))
        flash(f'Usuário cadastrado: {nome}. Email institucional: {msg_inst}. Envio para flaskaulas: {msg_flask}', 'success')

        return redirect(url_for('index'))

    # GET: lista todos; última inscrição define o "Olá, X!"
    users = User.query.order_by(User.id).all()
    greeting = users[-1].nome if users else 'Stranger'
    return render_template('index.html', users=users, greeting=greeting)

if __name__ == '__main__':
    app.run(debug=True)
