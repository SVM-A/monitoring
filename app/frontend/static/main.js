document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('loginForm');
    const errorDiv = document.getElementById('errorMessage');
    errorDiv.style.display = 'none';

    form.addEventListener('submit', async function(e) {
        e.preventDefault();

        const username = form.username.value;
        const password = form.password.value;
        errorDiv.style.display = 'none';


        try {
            const formData = new URLSearchParams();
            formData.append('username', username);
            formData.append('password', password);
            const response = await fetch(window.location.pathname, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                body: formData,
                redirect: 'manual'  // Обрабатываем редирект вручную
            });

            if (response.status === 303 || response.status === 0) {
                // Редирект (303) или успешный запрос
                window.location.reload();
            } else if (response.status === 401) {
                errorDiv.style.display = 'block';
            } else {
                console.error('Unexpected status:', response.status);
                errorDiv.textContent = 'Unexpected error occurred';
                errorDiv.style.display = 'block';
            }
        } catch (error) {
            errorDiv.textContent = 'Network error. Please try again.';
            errorDiv.style.display = 'block';
            console.error('Error:', error);
        }
    });
});