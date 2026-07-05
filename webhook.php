<?php
/**
 * signup-monitor — Mastodon → Matrix admin forwarder
 *
 * Receives Mastodon admin webhook events (account.created, report.created)
 * and forwards them as messages into a Matrix room using a bot account.
 *
 * Config lives in .env (see .env.example). No dependencies, no build step:
 * point a PHP-FPM vhost at this file and register the URL as a Mastodon
 * admin webhook (Admin → Settings → Webhooks).
 *
 * Mastodon admin pages referenced in messages:
 * - Reports:          {MASTODON_BASE_URL}/admin/reports
 * - Pending accounts: {MASTODON_BASE_URL}/admin/accounts?status=pending
 */

// --- Minimal .env loader (zero dependencies) --------------------------------
$env_path = __DIR__ . '/.env';
if ( is_readable( $env_path ) ) {
    foreach ( file( $env_path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES ) as $line ) {
        if ( $line === '' || $line[0] === '#' ) {
            continue;
        }
        if ( strpos( $line, '=' ) === false ) {
            continue;
        }
        list( $key, $value ) = explode( '=', $line, 2 );
        $key   = trim( $key );
        $value = trim( $value );
        // Strip optional surrounding quotes.
        if ( strlen( $value ) >= 2 && ( $value[0] === '"' || $value[0] === "'" ) && substr( $value, -1 ) === $value[0] ) {
            $value = substr( $value, 1, -1 );
        }
        if ( getenv( $key ) === false ) {
            putenv( "$key=$value" );
            $_ENV[ $key ] = $value;
        }
    }
}

function env( $key, $default = '' ) {
    $val = getenv( $key );
    return $val === false ? $default : $val;
}

// --- Configuration ----------------------------------------------------------
$matrix_base_url         = rtrim( env( 'MATRIX_BASE_URL', 'https://chat.mementomori.social' ), '/' );
$matrix_access_token     = env( 'MATRIX_ACCESS_TOKEN' );
$matrix_room_id          = env( 'MATRIX_ROOM_ID' );
$mastodon_base_url       = rtrim( env( 'MASTODON_BASE_URL', 'https://mementomori.social' ), '/' );
$mastodon_signing_secret = env( 'MASTODON_SIGNING_SECRET' );
$ping_plain              = env( 'PING_PLAIN', '@rolle' );
$ping_html               = env( 'PING_HTML', '<a href="https://matrix.to/#/@rolle:chat.mementomori.social">@rolle</a>' );
$log_file                = env( 'LOG_FILE', __DIR__ . '/signup-monitor.log' );
$debug                   = filter_var( env( 'DEBUG', 'false' ), FILTER_VALIDATE_BOOLEAN );

// --- Logging (PII-safe by default) ------------------------------------------
function log_message( $msg ) {
    global $log_file;
    $timestamp = date( 'Y-m-d H:i:s' );
    @file_put_contents( $log_file, "[$timestamp] $msg\n", FILE_APPEND );
}

// --- Only accept POST -------------------------------------------------------
if ( $_SERVER['REQUEST_METHOD'] !== 'POST' ) {
    http_response_code( 405 );
    echo 'Only POST requests are allowed.';
    exit;
}

// --- Read + parse payload ---------------------------------------------------
$input = file_get_contents( 'php://input' );
$data  = json_decode( $input, true );

if ( $debug ) {
    log_message( 'Raw input: ' . $input );
}

// --- Optional shared-secret check -------------------------------------------
// Mastodon sends the webhook secret; if a secret is configured we require a
// matching Signature header. Left tolerant (matches the original behaviour)
// so an instance without header signing keeps working.
$signature_header = $_SERVER['HTTP_SIGNATURE'] ?? '';
if ( $signature_header === '' ) {
    log_message( 'Warning: no Signature header present' );
} elseif ( $mastodon_signing_secret !== '' && ! hash_equals( $mastodon_signing_secret, $signature_header ) ) {
    log_message( 'Error: invalid signature' );
    http_response_code( 403 );
    echo 'Forbidden: invalid signature';
    exit;
}

if ( ! $data || ! isset( $data['event'] ) ) {
    http_response_code( 400 );
    echo 'Bad request';
    exit;
}

$event  = $data['event'];
$object = $data['object'] ?? null;

// --- Build message per event type -------------------------------------------
$plain_message = '';
$html_message  = '';

switch ( $event ) {
    case 'report.created':
        $plain_message  = "🚨 New report\n";
        $plain_message .= 'Category: ' . ( $object['category'] ?? 'Unknown' ) . "\n";
        $plain_message .= 'Comment: ' . ( $object['comment'] ?? 'No comment' ) . "\n";
        if ( isset( $object['target_account'] ) ) {
            $plain_message .= 'Reported account: @' . $object['target_account']['username'] .
                              '@' . $object['target_account']['domain'] . "\n";
        }
        $plain_message .= "\nReport link: $mastodon_base_url/admin/reports/" . $object['id'] . "\n";
        $plain_message .= "\n$ping_plain";

        $html_message  = '<strong>🚨 New report</strong><br>';
        $html_message .= '<strong>Category:</strong> ' . htmlspecialchars( $object['category'] ?? 'Unknown' ) . '<br>';
        $html_message .= '<strong>Comment:</strong> ' . htmlspecialchars( $object['comment'] ?? 'No comment' ) . '<br>';
        if ( isset( $object['target_account'] ) ) {
            $html_message .= '<strong>Reported account:</strong> @' .
                             htmlspecialchars( $object['target_account']['username'] ) .
                             '@' . htmlspecialchars( $object['target_account']['domain'] ) . '<br>';
        }
        $html_message .= "<a href='$mastodon_base_url/admin/reports/" . $object['id'] . "'>View report</a><br>";
        $html_message .= '<br><p>Ping ' . $ping_html . '</p>';
        break;

    case 'account.created':
        $plain_message  = "👤 New user signup\n";
        $plain_message .= 'Username: @' . ( $object['username'] ?? 'Unknown' ) . "\n";
        $plain_message .= 'Email: ' . ( $object['email'] ?? 'No email' ) . "\n";
        if ( ! empty( $object['invite_request'] ) ) {
            $plain_message .= 'Invite request: ' . $object['invite_request'] . "\n";
        }
        $plain_message .= "\nApproval link: $mastodon_base_url/admin/accounts?status=pending\n";
        $plain_message .= "\n$ping_plain";

        $html_message  = '<strong>👤 New signup request</strong><br>';
        $html_message .= '<strong>Username:</strong> @' . htmlspecialchars( $object['username'] ?? 'Unknown' ) . '<br>';
        $html_message .= '<strong>Email:</strong> ' . htmlspecialchars( $object['email'] ?? 'No email' ) . '<br>';
        if ( ! empty( $object['invite_request'] ) ) {
            $html_message .= '<strong>Invite request:</strong> ' . htmlspecialchars( $object['invite_request'] ) . '<br>';
        }
        $html_message .= "<a href='$mastodon_base_url/admin/accounts?status=pending'>View pending accounts</a><br>";
        $html_message .= '<br><p>Ping ' . $ping_html . '</p>';
        break;

    default:
        $plain_message = "Received event: $event";
        $html_message  = 'Received event: ' . htmlspecialchars( $event );
        break;
}

// --- Forward to Matrix ------------------------------------------------------
if ( $plain_message !== '' ) {
    $matrix_url = "$matrix_base_url/_matrix/client/r0/rooms/" .
                  rawurlencode( $matrix_room_id ) . '/send/m.room.message';

    $matrix_payload = json_encode([
        'msgtype'        => 'm.text',
        'body'           => $plain_message,
        'format'         => 'org.matrix.custom.html',
        'formatted_body' => $html_message,
    ]);

    $ch = curl_init( $matrix_url );
    curl_setopt( $ch, CURLOPT_CUSTOMREQUEST, 'POST' );
    curl_setopt( $ch, CURLOPT_POSTFIELDS, $matrix_payload );
    curl_setopt( $ch, CURLOPT_RETURNTRANSFER, true );
    curl_setopt( $ch, CURLOPT_HTTPHEADER, [
        'Authorization: Bearer ' . $matrix_access_token,
        'Content-Type: application/json',
    ]);

    $result    = curl_exec( $ch );
    $http_code = curl_getinfo( $ch, CURLINFO_HTTP_CODE );
    curl_close( $ch );

    // Log the outcome without PII (event + Matrix HTTP status only).
    log_message( "event=$event matrix_http=$http_code" );
    if ( $http_code < 200 || $http_code >= 300 ) {
        log_message( "Matrix error body: $result" );
    }
}
