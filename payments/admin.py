from django.contrib import admin

from payments.models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('asaas_payment_id', 'registration', 'status', 'billing_type', 'value', 'due_date', 'paid_at')
    list_filter = ('status', 'billing_type', 'due_date', 'paid_at')
    search_fields = ('asaas_payment_id', 'registration__athlete_name', 'registration__cpf')
    readonly_fields = ('created_at', 'updated_at', 'payload')
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'registration',
                    'customer_id',
                    'asaas_payment_id',
                    'status',
                    'billing_type',
                    'value',
                    'due_date',
                    'paid_at',
                    'invoice_url',
                    'bank_slip_url',
                )
            },
        ),
        (
            'PIX',
            {'fields': ('pix_qr_code_image', 'pix_copy_and_paste')},
        ),
        (
            'Outros dados',
            {'fields': ('external_reference', 'payload', 'created_at', 'updated_at')},
        ),
    )
