import re

html_path = 'web/avatar-experimental.html'
with open(html_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Include getnet.js script tag in head if not present
if '<script src="getnet.js"></script>' not in content:
    content = content.replace('<script src="client.js"></script>', '<script src="getnet.js"></script>\n    <script src="client.js"></script>')

# 2. Update CSS for cart-floating-widget (move to bottom-right corner)
old_cart_css = re.search(r'\.cart-floating-widget\s*\{[^}]+\}', content)
if old_cart_css:
    new_cart_css = """.cart-floating-widget {
            position: absolute;
            bottom: 24px;
            right: 24px;
            z-index: 40;
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 18px;
            border-radius: 9999px;
            background: linear-gradient(135deg, rgba(0, 47, 108, 0.95), rgba(0, 169, 224, 0.92));
            border: 1.5px solid rgba(255, 255, 255, 0.35);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            color: #ffffff;
            font-family: inherit;
            cursor: pointer;
            box-shadow: 0 8px 25px rgba(0, 47, 108, 0.45), 0 0 20px rgba(0, 169, 224, 0.35);
            transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .cart-floating-widget:hover {
            background: linear-gradient(135deg, rgba(0, 47, 108, 1), rgba(0, 169, 224, 1));
            border-color: #ffffff;
            transform: translateY(-3px) scale(1.04);
            box-shadow: 0 12px 30px rgba(0, 47, 108, 0.55), 0 0 25px rgba(0, 169, 224, 0.5);
        }
        .cart-floating-widget:active {
            transform: translateY(0) scale(0.98);
        }"""
    content = content.replace(old_cart_css.group(0), new_cart_css, 1)

# 3. Update checkout overlay CSS to official Paris.cl look & feel
old_checkout_css_block = re.search(r'/\* ══════════════════════════════════════════════════════════════════════\s*CHECKOUT EMBEBIDO A PANTALLA COMPLETA.*?(?=/\* ── Debug log panel)', content, re.DOTALL)
if old_checkout_css_block:
    new_checkout_css_block = """/* ══════════════════════════════════════════════════════════════════════
           CHECKOUT EMBEBIDO A PANTALLA COMPLETA (ESTILO WWW.PARIS.CL)
           ══════════════════════════════════════════════════════════════════════ */
        .checkout-overlay {
            position: fixed;
            inset: 0;
            z-index: 1000;
            background: rgba(0, 25, 60, 0.85);
            backdrop-filter: blur(18px);
            -webkit-backdrop-filter: blur(18px);
            display: none;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.28s ease;
            overflow-y: auto;
            color: #1e293b;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        }
        .checkout-overlay.open {
            display: flex;
            opacity: 1;
            pointer-events: auto;
        }
        .checkout-container {
            width: 100%;
            max-width: 1140px;
            margin: auto;
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 20px;
            min-height: 100vh;
            box-sizing: border-box;
        }
        .checkout-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 16px 24px;
            background: #002f6c;
            border-radius: 16px;
            box-shadow: 0 4px 20px rgba(0, 47, 108, 0.25);
            color: #ffffff;
        }
        .checkout-brand {
            display: flex;
            align-items: center;
            gap: 14px;
        }
        .brand-logo-img {
            font-size: 26px;
            font-weight: 900;
            letter-spacing: -0.02em;
            color: #00a9e0;
            text-transform: lowercase;
            font-family: inherit;
        }
        .brand-divider {
            color: rgba(255, 255, 255, 0.35);
            font-size: 18px;
        }
        .brand-store {
            font-size: 14px;
            font-weight: 600;
            color: #f1f5f9;
            letter-spacing: 0.02em;
        }
        .header-pos-pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 12px;
            border-radius: 9999px;
            font-size: 11px;
            font-weight: 700;
            background: rgba(0, 169, 224, 0.2);
            color: #38bdf8;
            border: 1px solid rgba(0, 169, 224, 0.4);
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .header-pos-pill.online {
            background: rgba(16, 185, 129, 0.2);
            color: #34d399;
            border-color: rgba(16, 185, 129, 0.5);
        }
        .checkout-close-btn {
            background: rgba(255, 255, 255, 0.12);
            border: 1px solid rgba(255, 255, 255, 0.25);
            color: #ffffff;
            padding: 8px 18px;
            border-radius: 9999px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .checkout-close-btn:hover {
            background: #00a9e0;
            border-color: #00a9e0;
            transform: scale(1.02);
        }

        .checkout-body {
            display: grid;
            grid-template-columns: 1.35fr 1fr;
            gap: 24px;
            flex: 1;
        }
        @media (max-width: 860px) {
            .checkout-body {
                grid-template-columns: 1fr;
            }
        }

        /* Columna Izquierda: Bolsa de compras */
        .checkout-left {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 16px;
            padding: 22px;
            display: flex;
            flex-direction: column;
            gap: 16px;
            box-shadow: 0 4px 20px rgba(0, 47, 108, 0.06);
        }
        .checkout-section-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding-bottom: 14px;
            border-bottom: 1.5px solid #f1f5f9;
        }
        .checkout-section-header h2 {
            margin: 0;
            font-size: 18px;
            font-weight: 800;
            color: #002f6c;
        }
        .btn-clear-cart {
            background: none;
            border: none;
            color: #e4002b;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            padding: 4px 8px;
            border-radius: 6px;
            transition: all 0.2s;
        }
        .btn-clear-cart:hover {
            background: #fff1f2;
            text-decoration: underline;
        }
        .checkout-cart-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
            max-height: 520px;
            overflow-y: auto;
            padding-right: 4px;
        }
        .checkout-item-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 14px 16px;
            gap: 14px;
            transition: all 0.2s ease;
        }
        .checkout-item-row:hover {
            border-color: #cbd5e1;
            background: #ffffff;
            box-shadow: 0 2px 10px rgba(0, 47, 108, 0.04);
        }
        .chk-item-info {
            flex: 1;
            min-width: 0;
        }
        .chk-item-title {
            font-size: 14px;
            font-weight: 700;
            color: #002f6c;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .chk-item-sub {
            font-size: 12px;
            color: #64748b;
            margin-top: 3px;
        }
        .chk-item-controls {
            display: flex;
            align-items: center;
            gap: 8px;
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            padding: 2px 6px;
        }
        .chk-qty-btn {
            width: 26px;
            height: 26px;
            border-radius: 4px;
            background: none;
            border: none;
            color: #002f6c;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-weight: 800;
            font-size: 15px;
            transition: background 0.15s;
        }
        .chk-qty-btn:hover {
            background: #e2e8f0;
        }
        .chk-item-qty {
            font-size: 13px;
            font-weight: 700;
            min-width: 18px;
            text-align: center;
            color: #0f172a;
        }
        .chk-item-price {
            font-size: 15px;
            font-weight: 800;
            color: #002f6c;
            min-width: 80px;
            text-align: right;
        }
        .chk-item-remove {
            background: none;
            border: none;
            color: #94a3b8;
            cursor: pointer;
            font-size: 16px;
            padding: 4px 8px;
            border-radius: 6px;
            line-height: 1;
            transition: all 0.2s;
        }
        .chk-item-remove:hover {
            color: #e4002b;
            background: #fff1f2;
        }
        .chk-empty-cart {
            text-align: center;
            padding: 50px 20px;
            color: #64748b;
            font-size: 14px;
            font-weight: 500;
        }

        /* Columna Derecha: Resumen de compra */
        .checkout-right {
            display: flex;
            flex-direction: column;
            gap: 16px;
        }
        .checkout-summary-card {
            background: #ffffff;
            border: 1.5px solid #e2e8f0;
            border-radius: 16px;
            padding: 22px;
            display: flex;
            flex-direction: column;
            gap: 14px;
            box-shadow: 0 4px 20px rgba(0, 47, 108, 0.08);
        }
        .checkout-summary-card h3 {
            margin: 0;
            font-size: 17px;
            font-weight: 800;
            color: #002f6c;
            padding-bottom: 10px;
            border-bottom: 1.5px solid #f1f5f9;
        }
        .summary-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 13px;
            color: #475569;
        }
        .summary-row.discount {
            color: #e4002b;
            font-weight: 700;
        }
        .summary-row.discount strong {
            color: #e4002b;
        }
        .summary-divider {
            height: 1px;
            background: #e2e8f0;
            margin: 6px 0;
        }
        .summary-total-row {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            font-size: 15px;
            font-weight: 800;
            color: #002f6c;
            padding: 4px 0;
        }
        .summary-total-amount {
            font-size: 24px;
            font-weight: 900;
            color: #002f6c;
            letter-spacing: -0.02em;
        }
        .cenco-points-badge {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
            background: #fffbeb;
            border: 1px solid #fde68a;
            border-radius: 8px;
            font-size: 12px;
            color: #92400e;
            font-weight: 600;
        }
        .cenco-points-icon {
            font-size: 14px;
        }

        .payment-selection-section {
            display: flex;
            flex-direction: column;
            gap: 8px;
            margin-top: 4px;
        }
        .payment-selection-section h4 {
            margin: 0;
            font-size: 13px;
            font-weight: 700;
            color: #002f6c;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .payment-methods-grid {
            display: flex;
            gap: 10px;
        }
        .payment-method-card {
            flex: 1;
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 12px;
            border-radius: 10px;
            background: #f8fafc;
            border: 1.5px solid #cbd5e1;
            cursor: pointer;
            transition: all 0.2s ease;
            text-align: left;
        }
        .payment-method-card:hover {
            border-color: #00a9e0;
            background: #f0f9ff;
        }
        .payment-method-card.active {
            border-color: #00a9e0;
            background: #f0f9ff;
            box-shadow: 0 0 0 2px rgba(0, 169, 224, 0.2);
        }
        .pm-icon {
            font-size: 20px;
        }
        .pm-info {
            display: flex;
            flex-direction: column;
        }
        .pm-title {
            font-size: 12px;
            font-weight: 700;
            color: #002f6c;
        }
        .pm-sub {
            font-size: 11px;
            color: #64748b;
        }

        .btn-checkout-pay {
            width: 100%;
            padding: 14px 20px;
            border-radius: 12px;
            background: linear-gradient(135deg, #00a9e0, #0082c8);
            border: none;
            color: #ffffff;
            font-size: 15px;
            font-weight: 800;
            cursor: pointer;
            box-shadow: 0 4px 18px rgba(0, 169, 224, 0.4);
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            margin-top: 4px;
        }
        .btn-checkout-pay:hover:not(:disabled) {
            background: linear-gradient(135deg, #0096c7, #0077b6);
            transform: translateY(-2px);
            box-shadow: 0 6px 22px rgba(0, 169, 224, 0.55);
        }
        .btn-checkout-pay:active:not(:disabled) {
            transform: translateY(0);
        }
        .btn-checkout-pay:disabled {
            opacity: 0.55;
            cursor: not-allowed;
            box-shadow: none;
        }

        /* Caja interactiva POS Getnet */
        .pos-interactive-box {
            display: flex;
            flex-direction: column;
            align-items: center;
            text-align: center;
            padding: 24px 16px;
            background: #f0f9ff;
            border: 2px dashed #00a9e0;
            border-radius: 14px;
            gap: 12px;
            animation: posPulse 2.5s infinite alternate;
        }
        @keyframes posPulse {
            0% { border-color: #00a9e0; background: #f0f9ff; }
            100% { border-color: #0284c7; background: #e0f2fe; }
        }
        .pos-status-spinner {
            width: 38px;
            height: 38px;
            border: 3.5px solid rgba(0, 169, 224, 0.25);
            border-top-color: #00a9e0;
            border-radius: 50%;
            animation: spin 0.9s linear infinite;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .pos-status-title {
            font-size: 16px;
            font-weight: 800;
            color: #002f6c;
        }
        .pos-status-instruction {
            font-size: 13px;
            color: #475569;
            max-width: 320px;
            line-height: 1.4;
        }
        .pos-interactive-amount {
            font-size: 26px;
            font-weight: 900;
            color: #002f6c;
            letter-spacing: -0.02em;
        }
        .pos-cancel-btn {
            background: #ffffff;
            border: 1px solid #cbd5e1;
            color: #e4002b;
            padding: 6px 16px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .pos-cancel-btn:hover {
            background: #fff1f2;
            border-color: #fca5a5;
        }

        /* Voucher de Venta (Ticket térmico oficial Paris / Getnet) */
        .checkout-voucher-view {
            display: flex;
            flex-direction: column;
            gap: 14px;
            align-items: center;
        }
        .voucher-success-header {
            text-align: center;
        }
        .voucher-success-header .success-icon {
            width: 48px;
            height: 48px;
            border-radius: 50%;
            background: #10b981;
            color: #ffffff;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            font-weight: 900;
            margin: 0 auto 8px auto;
            box-shadow: 0 4px 14px rgba(16, 185, 129, 0.35);
        }
        .voucher-success-header h3 {
            margin: 0;
            font-size: 18px;
            font-weight: 800;
            color: #002f6c;
            border: none;
            padding: 0;
        }
        .voucher-success-header p {
            margin: 4px 0 0 0;
            font-size: 12px;
            color: #10b981;
            font-weight: 700;
        }
        .voucher-ticket-paper {
            width: 100%;
            background: #ffffff;
            border: 1px solid #e2e8f0;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05);
            border-radius: 8px;
            padding: 16px;
            font-family: "Courier New", Courier, monospace;
            font-size: 11px;
            color: #1e293b;
            line-height: 1.5;
        }
        .voucher-ticket-paper .v-header {
            font-weight: 900;
            font-size: 13px;
            text-align: center;
            color: #002f6c;
        }
        .voucher-ticket-paper .v-sub {
            text-align: center;
            font-size: 10px;
            color: #64748b;
        }
        .voucher-ticket-paper .v-line {
            text-align: center;
            color: #cbd5e1;
            letter-spacing: -1px;
            margin: 4px 0;
        }
        .voucher-ticket-paper .v-row {
            display: flex;
            justify-content: space-between;
        }
        .voucher-ticket-paper .v-row.total {
            font-weight: 900;
            font-size: 13px;
            color: #002f6c;
            padding-top: 4px;
        }
        .voucher-ticket-paper .v-footer {
            text-align: center;
            font-size: 10px;
            color: #64748b;
            margin-top: 8px;
            font-weight: bold;
        }
        .btn-finish-checkout {
            width: 100%;
            padding: 12px 18px;
            border-radius: 10px;
            background: #002f6c;
            border: none;
            color: #ffffff;
            font-size: 14px;
            font-weight: 800;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .btn-finish-checkout:hover {
            background: #001f47;
            transform: translateY(-1px);
        }
        \n"""
    content = content.replace(old_checkout_css_block.group(0), new_checkout_css_block, 1)

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("HTML CSS and script tag updated successfully.")
