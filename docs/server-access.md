# Доступ к публичному учебному стенду

`https://112.rzd-learning.ru` закрыт одним общим паролем HTTP Basic Auth на Nginx.
Это временный шлюз перед учебной аутентификацией приложения. Он защищает
статические страницы, REST, Socket.IO и `/health`; HTTP перенаправляется на HTTPS.

## Однократная настройка сервера

Действующий виртуальный хост находится в
`/etc/nginx/sites-enabled/112.rzd-learning.ru.conf`. Перед изменением проверьте
`sudo nginx -T` и `sudo ss -ltnp`: backend должен слушать только `127.0.0.1:8112`,
а другие виртуальные хосты и порты не должны отдавать этот тренажёр.

Создайте пароль, отличный от паролей сервера, и файл с его хешем. Следующие
команды выполняйте в Bash (`bash` на сервере). Секрет вводится интерактивно и
не попадает в историю команд:

```bash
sudo install -o root -g www-data -m 0640 /dev/null /etc/nginx/ut112.htpasswd
read -r -s -p 'Пароль для UT112: ' UT112_PASSWORD; printf '\n'
UT112_HASH="$(printf '%s' "$UT112_PASSWORD" | openssl passwd -6 -stdin)"
unset UT112_PASSWORD
printf 'ut112:%s\n' "$UT112_HASH" | sudo tee /etc/nginx/ut112.htpasswd >/dev/null
unset UT112_HASH
```

Установите версию `deploy/nginx/112.rzd-learning.ru.conf` из защищённой ветки.
На текущем сервере `sites-enabled` был связан непосредственно с Git checkout;
переключите эту ссылку на `sites-available`, чтобы следующий `git reset` при
деплое не снял защиту до перечитывания Nginx:

```bash
sudo install -o root -g root -m 0644 \
    deploy/nginx/112.rzd-learning.ru.conf \
    /etc/nginx/sites-available/112.rzd-learning.ru.conf
sudo ln -sfn /etc/nginx/sites-available/112.rzd-learning.ru.conf \
    /etc/nginx/sites-enabled/112.rzd-learning.ru.conf
sudo nginx -t
sudo systemctl reload nginx
```

Скрипт `scripts/deploy-server.sh` при последующих деплоях устанавливает
конфигурацию из проверенного коммита в `sites-available`, проверяет её и
перечитывает Nginx. Файл `ut112.htpasswd` остаётся только на сервере.

После успешного CI для коммита в `main` workflow `Deploy production` передаёт
версию этого скрипта из проверенного коммита на сервер через SSH. Скрипт
принимает только текущий коммит `main`,
применяет миграции и идемпотентный демонстрационный seed, собирает frontend,
перезапускает backend и проверяет доступ. Результат виден в GitHub Actions;
проверки PR и сборка портативных архивов серверный деплой не запускают.

## Проверка и смена пароля

```bash
for path in / /api/users/demo '/socket.io/?EIO=4&transport=polling' /health; do
    curl -sS -o /dev/null -w "%{http_code} $path\n" "https://112.rzd-learning.ru$path"
done
curl -I http://112.rzd-learning.ru/
curl -u ut112 -fsS https://112.rzd-learning.ru/health
```

Без пароля все четыре HTTPS-запроса должны вернуть `401`; HTTP должен
перенаправить на HTTPS; авторизованный `/health` должен вернуть `status: ok`.
В браузере после ввода пароля проверьте вход, запросы API и соединение
Socket.IO (WebSocket `101 Switching Protocols`).

Для смены пароля повторно введите новый секрет и перезапишите строку `ut112`
в том же файле; Nginx перечитывает файл паролей без смены конфигурации. Не
передавайте пароль через Git, CI, аргументы процессов или URL.
