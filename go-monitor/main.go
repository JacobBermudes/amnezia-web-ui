package main

import (
	"bytes"
	"net/http"
	"os/exec"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

type PeerStat struct {
	PublicKey       string `json:"public_key"`
	Endpoint        string `json:"endpoint"`
	LatestHandshake int64  `json:"latest_handshake"`
	TransferRx      int64  `json:"transfer_rx"`
	TransferTx      int64  `json:"transfer_tx"`
	IsActive        bool   `json:"is_active"`
}

type ServerLoad struct {
	TotalRx     int64               `json:"total_rx_bytes"`
	TotalTx     int64               `json:"total_tx_bytes"`
	ActivePeers int                 `json:"active_peers"`
	Peers       map[string]PeerStat `json:"peers"`
}

func getAWGLoad(interfaceName string) (*ServerLoad, error) {
	cmd := exec.Command("awg", "show", interfaceName, "dump")
	var out bytes.Buffer
	cmd.Stdout = &out

	if err := cmd.Run(); err != nil {
		return nil, err
	}

	lines := strings.Split(strings.TrimSpace(out.String()), "\n")
	load := &ServerLoad{
		Peers: make(map[string]PeerStat),
	}

	if len(lines) <= 1 {
		return load, nil
	}

	for _, line := range lines[1:] {
		fields := strings.Split(line, "\t")
		if len(fields) < 8 {
			continue
		}

		pubKey := fields[1]
		endpoint := fields[3]
		handshake, _ := strconv.ParseInt(fields[5], 10, 64)
		rx, _ := strconv.ParseInt(fields[6], 10, 64)
		tx, _ := strconv.ParseInt(fields[7], 10, 64)

		isActive := (time.Now().Unix() - handshake) < 180

		load.Peers[pubKey] = PeerStat{
			PublicKey:       pubKey,
			Endpoint:        endpoint,
			LatestHandshake: handshake,
			TransferRx:      rx,
			TransferTx:      tx,
			IsActive:        isActive,
		}

		load.TotalRx += rx
		load.TotalTx += tx
		if isActive {
			load.ActivePeers++
		}
	}

	return load, nil
}

func main() {
	gin.SetMode(gin.ReleaseMode)
	r := gin.Default()

	r.GET("/api/v1/load", func(c *gin.Context) {
		server_id := c.Query("server")
		if server_id == "" {
			c.JSON(http.StatusBadRequest, gin.H{"error": "server parameter is required"})
			return
		}
		load, err := getAWGLoad("wg-" + server_id)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to fetch AWG stats: " + err.Error()})
			return
		}
		c.JSON(http.StatusOK, load)
	})

	if err := r.Run(":8080"); err != nil {
		panic(err)
	}
}
