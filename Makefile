.PHONY: test eda run-auth run-product run-cart run-order run-notification
test:
	pytest -q
eda:
	python analytics/eda.py
run-auth:
	./scripts/run_auth.sh
run-product:
	./scripts/run_product.sh
run-cart:
	./scripts/run_cart.sh
run-order:
	./scripts/run_order.sh
run-notification:
	./scripts/run_notification.sh
