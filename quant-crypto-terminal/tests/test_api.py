from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from fastapi.testclient import TestClient

from app import db
from app.main import app, market
from app.market import Quote


def boot(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path/'api.db')
    db.init_db()
    market.quotes = {
        'BTC': Quote('BTC', Decimal('80.00'), Decimal('1.2'), Decimal('100'), 10**15, 'test_fixture'),
        'ETH': Quote('ETH', Decimal('1000.00'), Decimal('1'), Decimal('100'), 10**15, 'test_fixture'),
        'SOL': Quote('SOL', Decimal('10.00'), Decimal('1'), Decimal('100'), 10**15, 'test_fixture'),
    }


def test_http_order_and_portfolio(tmp_path, monkeypatch):
    boot(tmp_path, monkeypatch)
    with TestClient(app) as client:
        r=client.get('/api/portfolio'); assert r.status_code==200
        r=client.post('/api/orders', json={'asset':'BTC','side':'BUY','quantity':'1','client_order_id':'http-test-12345678'})
        assert r.status_code==200
        assert r.json()['execution_price']=='80.00'
        r=client.get('/api/portfolio'); assert r.json()['holdings'][0]['quantity']=='1'


def test_concurrent_buys_do_not_overspend(tmp_path, monkeypatch):
    boot(tmp_path, monkeypatch)
    con=db._connect()
    con.execute("UPDATE accounts SET cash_cents=10000 WHERE id='demo'")
    con.commit(); con.close()
    with TestClient(app) as client:
        def do(i):
            return client.post('/api/orders', json={'asset':'BTC','side':'BUY','quantity':'1','client_order_id':f'concurrent-{i}-12345678'})
        with ThreadPoolExecutor(max_workers=2) as ex:
            results=list(ex.map(do,[1,2]))
        statuses=[r.status_code for r in results]
        assert sorted(statuses)==[200,400]
        p=client.get('/api/portfolio').json()
        assert Decimal(p['cash']) >= Decimal('19.00')
        btc=next(h for h in p['holdings'] if h['asset']=='BTC')
        assert Decimal(btc['quantity']) == Decimal('1')
