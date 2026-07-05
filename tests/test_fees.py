from cardtracker.config import Settings
from cardtracker.fees import FeeModel, compute_net


def test_default_model_breakdown():
    model = FeeModel()
    b = compute_net(model, 100.0)
    # 13.25% of 100 plus 0.30 per order
    assert b.total_fees == 13.55
    assert b.net == 86.45
    assert len(b.lines) == 2


def test_fvf_applies_to_shipping_and_tax():
    model = FeeModel(final_value_pct=10.0, per_order_fee=0.0)
    b = compute_net(model, 100.0, shipping_charged=10.0, tax_collected=8.0)
    # fee base 118, fee 11.80; seller keeps price + shipping only
    assert b.total_fees == 11.80
    assert b.gross_to_seller == 110.0
    assert b.net == 98.20


def test_fvf_flags_can_exclude_shipping_and_tax():
    model = FeeModel(final_value_pct=10.0, per_order_fee=0.0,
                     fvf_on_shipping=False, fvf_on_tax=False)
    b = compute_net(model, 100.0, shipping_charged=10.0, tax_collected=8.0)
    assert b.total_fees == 10.0
    assert b.net == 100.0


def test_promoted_and_processing_and_shipping_cost():
    model = FeeModel(final_value_pct=13.25, per_order_fee=0.30,
                     payment_pct=2.9, payment_fixed=0.30)
    b = compute_net(model, 200.0, shipping_cost=5.50, promoted_pct=2.0)
    fvf = round(200 * 0.1325, 2)          # 26.50
    promo = round(200 * 0.02, 2)          # 4.00
    processing = round(200 * 0.029 + 0.30, 2)  # 6.10
    assert b.total_fees == fvf + promo + 0.30 + processing
    assert b.net == 200.0 - b.total_fees - 5.50


def test_promoted_override_beats_model_default():
    model = FeeModel(final_value_pct=0.0, per_order_fee=0.0, promoted_pct=5.0)
    assert compute_net(model, 100.0).total_fees == 5.0
    assert compute_net(model, 100.0, promoted_pct=0.0).total_fees == 0.0


def test_model_from_settings():
    settings = Settings(fee_final_value_pct=12.0, fee_per_order=0.40,
                        fee_promoted_pct=2.0, fee_fvf_on_tax=False)
    model = FeeModel.from_settings(settings)
    assert model.final_value_pct == 12.0
    assert model.per_order_fee == 0.40
    assert model.promoted_pct == 2.0
    assert model.fvf_on_tax is False
