document.addEventListener('DOMContentLoaded', function () {


  const revenueCtx = document.getElementById('revenueChart');
  if (revenueCtx) {
    const dates = {{ chart_dates|safe }};
    const revenueData = {{ chart_revenue|safe }};
    const profitData = {{ chart_profit|safe }};

    new Chart(revenueCtx, {
      type: 'line',
      data: {
        labels: dates,
        datasets: [
          {
            label: 'Revenue',
            data: revenueData,
            borderColor: '#10B981',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            tension: 0.4,
            fill: true
          },
          {
            label: 'Gross Profit',
            data: profitData,
            borderColor: '#3B82F6',
            backgroundColor: 'rgba(59, 130, 246, 0.1)',
            tension: 0.4,
            fill: true
          }
        ]
      },
      options: {
        responsive: true,
        plugins: {
          legend: {
            display: true,
            position: 'top'
          },
          title: {
            display: true,
            text: 'Revenue & Gross Profit Trend'
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: {
              callback: value => 'KES ' + value.toLocaleString()
            }
          }
        }
      }
    });
  }

  // === Top Categories by Revenue (Bar Chart) ===
  const categoriesCtx = document.getElementById('categoriesChart');  // or 'brandsChart' if you kept the old ID
  if (categoriesCtx) {
    const categoryLabels = {{ category_names|safe }};
    const categoryData = {{ category_values|safe }};

    // Optional: colorful bars (cycle through palette)
    const colors = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#14B8A6', '#F97316', '#6366F1', '#84CC16'];

    new Chart(categoriesCtx, {
      type: 'bar',
      data: {
        labels: categoryLabels.length ? categoryLabels : ['No data'],
        datasets: [{
          label: 'Revenue',
          data: categoryLabels.length ? categoryData : [0],
          backgroundColor: categoryLabels.length 
            ? categoryData.map((_, i) => colors[i % colors.length])
            : '#9CA3AF',
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
          title: {
            display: true,
            text: 'Top Categories by Revenue'
          },
          tooltip: {
            callbacks: {
              label: context => `KES ${context.parsed.y.toLocaleString()}`
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: {
              callback: value => 'KES ' + value.toLocaleString()
            }
          }
        }
      }
    });
  }

});