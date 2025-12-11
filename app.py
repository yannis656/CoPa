from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime

app = Flask(__name__, static_folder='static')
CORS(app)

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'election_mister'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', 'azerty'),
    'port': os.getenv('DB_PORT', '5432')
}

def get_db():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print(f"Erreur de connexion à la base de données: {e}")
        raise

@app.route('/api/candidates', methods=['GET'])
def get_candidates():
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Extraire le numéro du candidat depuis l'ID (ex: '26miss1' -> '1', '26mister4' -> '4')
        cur.execute("""
            SELECT *, 
                   CAST(REGEXP_REPLACE(id, '[^0-9]', '', 'g') AS INTEGER) as candidate_number
            FROM candidates 
            ORDER BY categorie, candidate_number
        """)
        candidates = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(candidates)
    except Exception as e:
        print(f"Erreur dans get_candidates: {e}")
        return jsonify({'error': 'Erreur de connexion à la base de données'}), 500
    
@app.route('/api/candidates/<categorie>', methods=['GET'])
def get_candidates_by_category(categorie):
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT *, 
                   CAST(REGEXP_REPLACE(id, '[^0-9]', '', 'g') AS INTEGER) as candidate_number
            FROM candidates 
            WHERE categorie = %s 
            ORDER BY candidate_number
        """, (categorie,))
        candidates = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(candidates)
    except Exception as e:
        print(f"Erreur dans get_candidates_by_category: {e}")
        return jsonify({'error': 'Erreur de connexion à la base de données'}), 500

@app.route('/api/vote', methods=['POST'])
def submit_vote():
    data = request.json
    candidate_id = data.get('candidate_id')
    payment_method = data.get('payment_method')
    transaction_code = data.get('transaction_code')
    vote_count = data.get('vote_count', 1)
    
    if not all([candidate_id, payment_method, transaction_code]):
        return jsonify({'error': 'Données manquantes'}), 400
    
    amount = vote_count * 100
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Vérifier si le code de transaction existe déjà (insensible à la casse)
        cur.execute("""
            SELECT id, candidate_id, statut, created_at 
            FROM transactions 
            WHERE code_transaction_normalized = UPPER(%s)
        """, (transaction_code,))
        existing_transaction = cur.fetchone()
        
        if existing_transaction:
            transaction_id, existing_candidate_id, status, created_at = existing_transaction
            return jsonify({
                'error': 'Code de transaction déjà utilisé',
                'exists': True,
                'transaction_id': transaction_id,
                'candidate_id': existing_candidate_id,
                'status': status,
                'created_at': created_at.isoformat() if created_at else None
            }), 409
        
        # Insérer la nouvelle transaction
        cur.execute("""
            INSERT INTO transactions (candidate_id, methode_paiement, code_transaction, nombre_votes, montant)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (candidate_id, payment_method, transaction_code, vote_count, amount))
        
        transaction_id = cur.fetchone()[0]
        conn.commit()
        
        cur.close()
        conn.close()
        
        return jsonify({
            'message': 'Transaction enregistrée, en attente de validation',
            'transaction_id': transaction_id
        }), 201
        
    except psycopg2.errors.UniqueViolation as e:
        print(f"Violation de contrainte unique: {e}")
        if 'conn' in locals():
            conn.rollback()
        return jsonify({
            'error': 'Code de transaction déjà utilisé',
            'exists': True
        }), 409
    except Exception as e:
        print(f"Erreur dans submit_vote: {e}")
        if 'conn' in locals():
            conn.rollback()
            cur.close()
            conn.close()
        return jsonify({'error': 'Erreur de connexion à la base de données'}), 500

# Nouvel endpoint pour vérifier un code de transaction
@app.route('/api/check-transaction/<code>', methods=['GET'])
def check_transaction_code(code):
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT t.*, c.nom as candidate_name
            FROM transactions t
            LEFT JOIN candidates c ON t.candidate_id = c.id
            WHERE code_transaction_normalized = UPPER(%s)
            ORDER BY t.created_at DESC
            LIMIT 1
        """, (code,))
        
        transaction = cur.fetchone()
        cur.close()
        conn.close()
        
        if transaction:
            return jsonify({
                'exists': True,
                'transaction': transaction
            })
        else:
            return jsonify({
                'exists': False
            })
            
    except Exception as e:
        print(f"Erreur dans check_transaction_code: {e}")
        return jsonify({'error': 'Erreur de vérification'}), 500

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    password = data.get('password')
    
    if not password:
        return jsonify({'error': 'Mot de passe requis'}), 400
    
    # Mot de passe simple pour la démo
    if password == '2025':
        return jsonify({'message': 'Connexion réussie', 'token': 'admin_token'}), 200
    else:
        return jsonify({'error': 'Mot de passe incorrect'}), 401

@app.route('/api/admin/transactions/pending', methods=['GET'])
def get_pending_transactions():
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT t.*, c.nom as candidate_name,
                   c.categorie as candidate_category,
                   CAST(REGEXP_REPLACE(c.id, '[^0-9]', '', 'g') AS INTEGER) as candidate_number
            FROM transactions t
            JOIN candidates c ON t.candidate_id = c.id
            WHERE t.statut = 'pending'
            ORDER BY t.created_at DESC
        """)
        transactions = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(transactions)
    except Exception as e:
        print(f"Erreur dans get_pending_transactions: {e}")
        return jsonify({'error': 'Erreur de connexion à la base de données'}), 500

@app.route('/api/admin/transactions/<int:transaction_id>/validate', methods=['POST'])
def validate_transaction(transaction_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("SELECT candidate_id, nombre_votes FROM transactions WHERE id = %s AND statut = 'pending'", (transaction_id,))
        result = cur.fetchone()
        
        if not result:
            return jsonify({'error': 'Transaction non trouvée'}), 404
        
        candidate_id, vote_count = result
        
        cur.execute("UPDATE candidates SET votes = votes + %s WHERE id = %s", (vote_count, candidate_id))
        cur.execute("UPDATE transactions SET statut = 'validated', validated_at = %s WHERE id = %s", (datetime.now(), transaction_id))
        conn.commit()
        
        cur.close()
        conn.close()
        return jsonify({'message': 'Transaction validée'}), 200
    except Exception as e:
        print(f"Erreur dans validate_transaction: {e}")
        if 'conn' in locals():
            conn.rollback()
            cur.close()
            conn.close()
        return jsonify({'error': 'Erreur de connexion à la base de données'}), 500

@app.route('/api/admin/transactions/<int:transaction_id>/reject', methods=['POST'])
def reject_transaction(transaction_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("UPDATE transactions SET statut = 'rejected', validated_at = %s WHERE id = %s", (datetime.now(), transaction_id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'message': 'Transaction rejetée'}), 200
    except Exception as e:
        print(f"Erreur dans reject_transaction: {e}")
        if 'conn' in locals():
            conn.rollback()
            cur.close()
            conn.close()
        return jsonify({'error': 'Erreur de connexion à la base de données'}), 500

@app.route('/api/ranking', methods=['GET'])
def get_ranking():
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT *, 
                   CAST(REGEXP_REPLACE(id, '[^0-9]', '', 'g') AS INTEGER) as candidate_number,
                   ROW_NUMBER() OVER (ORDER BY votes DESC, nom) as rank_position
            FROM candidates 
            ORDER BY votes DESC, nom
        """)
        ranking = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(ranking)
    except Exception as e:
        print(f"Erreur dans get_ranking: {e}")
        return jsonify({'error': 'Erreur de connexion à la base de données'}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Nombre total de candidats
        cur.execute("SELECT COUNT(*) FROM candidates")
        total_candidates = cur.fetchone()[0]
        
        # Total des votes
        cur.execute("SELECT SUM(votes) FROM candidates")
        total_votes = cur.fetchone()[0] or 0
        
        # Transactions par statut
        cur.execute("SELECT statut, COUNT(*) FROM transactions GROUP BY statut")
        transactions_stats = cur.fetchall()
        
        cur.close()
        conn.close()
        
        # Convertir en dictionnaire
        transactions_dict = {status: count for status, count in transactions_stats}
        
        return jsonify({
            'total_candidates': total_candidates,
            'total_votes': total_votes,
            'transactions': transactions_dict
        })
    except Exception as e:
        print(f"Erreur dans get_stats: {e}")
        return jsonify({'error': 'Erreur de connexion à la base de données'}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Endpoint pour vérifier la santé de l'API et de la BD"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return jsonify({'status': 'healthy', 'database': 'connected'}), 200
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'database': 'disconnected', 'error': str(e)}), 500
@app.route('/')
def serve_index():
    return send_from_directory('static', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

# Modifiez la dernière ligne pour la production
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
