package com.fitgains.app

import android.app.Activity
import android.content.Context
import android.graphics.Color
import android.os.Bundle
import android.util.Patterns
import android.view.ViewGroup
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Toast

/**
 * Thin WebView shell around a self-hosted FitGains instance.
 *
 * First launch asks for the server URL (the PWA manifest there makes the
 * experience app-grade); afterwards the app opens straight into the site.
 * Long-press the WebView to reopen the server settings.
 */
class MainActivity : Activity() {

    private lateinit var webView: WebView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val url = prefs().getString(KEY_URL, null)
        if (url.isNullOrBlank()) showUrlEntry() else showWebView(url)
    }

    private fun prefs() = getSharedPreferences("fitgains", Context.MODE_PRIVATE)

    private fun showUrlEntry() {
        val input = EditText(this).apply {
            hint = "https://your-fitgains-instance.example"
            inputType = android.text.InputType.TYPE_CLASS_TEXT or
                android.text.InputType.TYPE_TEXT_VARIATION_URI
        }
        val button = Button(this).apply {
            text = "Connect"
            setOnClickListener {
                var url = input.text.toString().trim().trimEnd('/')
                if (!url.startsWith("http")) url = "https://$url"
                if (Patterns.WEB_URL.matcher(url).matches()) {
                    prefs().edit().putString(KEY_URL, url).apply()
                    showWebView(url)
                } else {
                    Toast.makeText(
                        this@MainActivity,
                        "Enter a valid server URL",
                        Toast.LENGTH_LONG
                    ).show()
                }
            }
        }
        setContentView(
            LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(48, 96, 48, 48)
                addView(input)
                addView(button)
            }
        )
    }

    private fun showWebView(url: String) {
        webView = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(
                    view: WebView,
                    request: WebResourceRequest
                ) = false
            }
            // Long-press anywhere → reconfigure the server URL
            setOnLongClickListener {
                prefs().edit().remove(KEY_URL).apply()
                showUrlEntry()
                true
            }
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        }
        webView.loadUrl(url)
        setContentView(webView)
    }

    override fun onBackPressed() {
        if (::webView.isInitialized && webView.canGoBack()) {
            webView.goBack()
        } else {
            super.onBackPressed()
        }
    }

    override fun onDestroy() {
        if (::webView.isInitialized) webView.destroy()
        super.onDestroy()
    }

    private companion object {
        const val KEY_URL = "server_url"
    }
}
