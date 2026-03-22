document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.dynamic-product').forEach(select => {
        select.addEventListener('change', function() {
            const productId = this.value;
            if (productId) {
                fetch(`/api/products/${productId}/price/`)
                    .then(response => response.json())
                    .then(data => {
                        const priceField = this.closest('.inline-related').querySelector('.field-unit_cost_price input');
                        priceField.value = data.cost_price;
                    });
            }
        });
    });
});